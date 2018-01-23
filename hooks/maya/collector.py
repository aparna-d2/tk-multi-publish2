# Copyright (c) 2017 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

import os
import glob
import copy
import pprint

import maya.cmds as cmds
import maya.mel as mel
import sgtk
from sgtk import TankError

HookBaseClass = sgtk.get_hook_baseclass()


class MayaSessionCollector(HookBaseClass):
    """
    Collector that operates on the current maya session. Should
    inherit from the basic collector hook.
    """
    def __init__(self, parent):
        """
        Construction
        """
        # call base init
        super(MayaSessionCollector, self).__init__(parent)

        # cache the workfiles app
        self.__workfiles_app = self.parent.engine.apps.get("tk-multi-workfiles2")


    @property
    def settings_schema(self):
        """
        Dictionary defining the settings that this collector expects to receive
        through the settings parameter in the process_current_session and
        process_file methods.

        A dictionary on the following form::

            {
                "Settings Name": {
                    "type": "settings_type",
                    "default_value": "default_value",
                    "description": "One line description of the setting"
            }

        The type string should be one of the data types that toolkit accepts as
        part of its environment configuration.
        """
        schema = super(MayaSessionCollector, self).settings_schema
        schema["Work File Templates"] = {
            "type": "list",
            "values": {
                "type": "template",
                "description": "",
                "fields": ["context", "*"]
            },
            "default_value": [],
            "allows_empty": True,
            "description": "A list of templates to use to search for work files."
        }
        return schema


    def process_current_session(self, parent_item):
        """
        Analyzes the current session open in Maya and parents a
        subtree of items under the parent_item passed in.

        :param parent_item: Root item instance
        """
        items = []

        # create an item representing the current maya session
        session_item = self.collect_current_maya_session(parent_item)
        if session_item:
            items.append(session_item)

        # look at the render layers to find rendered images on disk
        items.extend(self.collect_rendered_images(session_item))

        # collect any scene geometry
        if cmds.ls(geometry=True, noIntermediate=True):
            items.extend(self.collect_session_geometry(session_item))

        # if we have work path templates, collect matching files to publish
        for work_template in self.settings["Work File Templates"].value:
            items.extend(self.collect_work_files(session_item, work_template))

        # Return the list of items
        return items


    def collect_current_maya_session(self, parent_item):
        """
        Analyzes the current session open in Maya and parents a subtree of items
        under the parent_item passed in.

        :param parent_item: Root item instance
        """
        # get the current path
        file_path = _session_path()
        if not file_path:
            # the session has not been saved before (no path determined).
            # provide a save button. the session will need to be saved before
            # validation will succeed.
            self.logger.warning(
                "The Maya scene has not been saved.",
                extra=self._get_save_as_action()
            )

        session_item = self._add_file_item(parent_item, file_path)

        if session_item:
            session_item.name = "Current Maya Session"

        # discover the project root which helps in discovery of other
        # publishable items
        project_root = cmds.workspace(q=True, rootDirectory=True)
        session_item.properties["project_root"] = project_root

        return session_item


    def collect_rendered_images(self, parent_item):
        """
        Creates items for any rendered images that can be identified by
        render layers in the file.

        :param parent_item: Parent Item instance
        :return:
        """
        items = []

        # iterate over defined render layers and query the render settings for
        # information about a potential render
        for layer in cmds.ls(type="renderLayer"):

            self.logger.info("Processing render layer: %s" % (layer,))

            # use the render settings api to get a path where the frame number
            # spec is replaced with a '*' which we can use to glob
            (frame_glob,) = cmds.renderSettings(
                genericFrameImageName="*",
                fullPath=True,
                layer=layer
            )

            # see if there are any files on disk that match this pattern
            rendered_paths = glob.glob(frame_glob)

            if rendered_paths:
                # we only need one path to publish, so take the first one and
                # let the base class collector handle it
                item = self._collect_file(parent_item, rendered_paths[0])
                if not item:
                    continue

                # the item has been created. update the display name to include
                # the an indication of what it is and why it was collected
                item.name = "Render Layer (%s)" % (layer,)

                # Store the layer as the item node
                item.properties["node"] = layer

                # Add the item to the list
                items.append(item)

        return items


    def collect_session_geometry(self, parent_item):
        """
        Creates items for session geometry to be exported.

        :param parent_item: Parent Item instance
        """
        geo_item = parent_item.create_item(
            "maya.geometry",
            "Geometry",
            "Maya Session Geometry",
            self
        )

        # get the icon path to display for this item
        icon_path = os.path.join(
            self.disk_location,
            os.pardir,
            "icons",
            "geometry.png"
        )

        geo_item.set_icon_from_path(icon_path)

        # Copy the parent session's properties
        geo_item.properties = copy.deepcopy(parent_item.properties)

        self.logger.info("Collected item: Maya Session Geometry")
        return [geo_item]


    def collect_work_files(self, parent_item, work_template):
        """
        Creates items for files matching the work path template
        """
        items = []
        try:
            work_paths = self._get_work_paths(parent_item, work_template)
            for work_path in work_paths:
                item = self._collect_file(parent_item, work_path)
                if not item:
                    continue

				# Track the current work template being processed
                item.properties["work_path_template"] = work_template

                # Add the item to the list
                items.append(item)

        except Exception as e:
            self.logger.warning("%s. Skipping..." % str(e))

        return items


    def _get_work_paths(self, parent_item, work_path_template):
        """
        Get paths matching the work path template using the supplied item's fields.

        :param parent_item: The item to determine the work path for
        :param work_path_template: The template string to resolve

        :return: A list of paths matching the resolved work path template for
            the supplied item

        Extracts the work path via the configured work templates
        if possible.
        """

        publisher = self.parent

        # Start with the item's fields
        fields = copy.deepcopy(parent_item.properties.get("fields", {}))

        work_tmpl = publisher.get_template_by_name(work_path_template)
        if not work_tmpl:
            # this template was not found in the template config!
            raise TankError("The Template '%s' does not exist!" % work_path_template)

        # First get the fields from the context
        try:
            fields.update(parent_item.context.as_template_fields(work_tmpl))
        except TankError as e:
            self.logger.warning(
                "Unable to get context fields for work_path_template.")

        # Get the paths from the template using the known fields
        self.logger.info(
            "Searching for file(s) matching: '%s'" % work_path_template,
            extra={
                "action_show_more_info": {
                    "label": "Show Info",
                    "tooltip": "Show more info",
                    "text": "Template: %s\nFields: %s" % (work_tmpl, fields)
                }
            }
        )
        return self.sgtk.abstract_paths_from_template(work_tmpl,
                                                      fields,
                                                      skip_missing_optional_keys=True)


    def _resolve_item_fields(self, item):
        """
        Helper method used to get fields that might not normally be defined in the context.
        Intended to be overridden by DCC-specific subclasses.
        """
        # If this is a maya session and we have the workfiles app defined...
        if item.type == "file.maya" and self.__workfiles_app:
            # Get work_path_template from the workfiles app for the item's context
            # Note: this needs to happen here instead of during item initialization
            # since the path may change if the context changes
            item.properties["work_path_template"] = \
                self.__workfiles_app.get_work_template(item.context).name

        # Now run the parent resolve method
        fields = super(MayaSessionCollector, self)._resolve_item_fields(item)

        node = item.properties.get("node")
        if node:
            # If not defined, set output field to the node name
            if "output" not in fields:
                fields["output"] = node

        return fields


    def _get_save_as_action(self):
        """
        Simple helper for returning a log action dict for saving the session
        """
        # default save callback
        callback = cmds.SaveScene

        # if workfiles2 is configured, use that for file save
        if self.__workfiles_app:
            callback = self.__workfiles_app.show_file_save_dlg

        return {
            "action_button": {
                "label": "Save As...",
                "tooltip": "Save the current session",
                "callback": callback
            }
        }


def _session_path():
    """
    Return the path to the current session
    :return:
    """
    path = cmds.file(query=True, sn=True)

    if isinstance(path, unicode):
        path = path.encode("utf-8")

    return path


def _save_session(path):
    """
    Save the current session to the supplied path.
    """

    # Maya can choose the wrong file type so we should set it here
    # explicitly based on the extension
    maya_file_type = None
    if path.lower().endswith(".ma"):
        maya_file_type = "mayaAscii"
    elif path.lower().endswith(".mb"):
        maya_file_type = "mayaBinary"

    cmds.file(rename=path)

    # save the scene:
    if maya_file_type:
        cmds.file(save=True, force=True, type=maya_file_type)
    else:
        cmds.file(save=True, force=True)
