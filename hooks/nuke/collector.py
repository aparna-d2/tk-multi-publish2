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
import nuke
import sgtk

HookBaseClass = sgtk.get_hook_baseclass()

# A look up of node types to parameters for finding outputs to publish
_NUKE_OUTPUTS = {
    "WriteTank": "file",
}


class NukeSessionCollector(HookBaseClass):
    """
    Collector that operates on the current nuke/nukestudio session. Should
    inherit from the basic collector hook.
    """
    def __init__(self, parent, **kwargs):
        """
        Construction
        """
        # call base init
        super(NukeSessionCollector, self).__init__(parent, **kwargs)

        # cache the write node and workfiles apps
        self.__write_node_app = self.parent.engine.apps.get("tk-nuke-writenode")
        self.__workfiles_app = self.parent.engine.apps.get("tk-multi-workfiles2")


    def process_current_session(self, settings, parent_item):
        """
        Analyzes the current session open in Nuke/NukeStudio and parents a
        subtree of items under the parent_item passed in.

        :param dict settings: Configured settings for this collector
        :param parent_item: Root item instance
        """
        items = []

        publisher = self.parent
        engine = publisher.engine

        if hasattr(engine, "studio_enabled") and engine.studio_enabled:
            # running nuke studio.
            self.collect_current_nukestudio_session(settings, parent_item)

            # since we're in NS, any additional collected outputs will be
            # parented under the root item
            session_item = parent_item
        else:
            # running nuke. ensure additional collected outputs are parented
            # under the session
            session_item = self.collect_current_nuke_session(settings, parent_item)

        # Add session_item to the list
        items.append(session_item)

        # Also collect any output node items
        items.extend(self.collect_node_outputs(settings, session_item))

        # Return the list of items
        return items


    def collect_current_nuke_session(self, settings, parent_item):
        """
        Analyzes the current session open in Nuke and parents a subtree of items
        under the parent_item passed in.

        :param dict settings: Configured settings for this collector
        :param parent_item: Root item instance
        """

        publisher = self.parent

        # get the current path
        file_path = _session_path()
        if not file_path:
            # the session has not been saved before (no path determined).
            # provide a save button. the session will need to be saved before
            # validation will succeed.
            self.logger.warning(
                "The Nuke script has not been saved.",
                extra=self._get_save_as_action()
            )

        session_item = super(NukeSessionCollector, self)._add_file_item(
            settings,
            parent_item,
            file_path
        )

        if session_item:
            session_item.name = "Current Nuke Session"

        return session_item


    def collect_current_nukestudio_session(self, settings, parent_item):
        """
        Analyzes the current session open in NukeStudio and parents a subtree of
        items under the parent_item passed in.

        :param dict settings: Configured settings for this collector
        :param parent_item: Root item instance
        """

        # import here since the hooks are imported into nuke and nukestudio.
        # hiero module is only available in later versions of nuke
        import hiero.core

        # go ahead and build the path to the icon for use by any projects
        icon_path = os.path.join(
            self.disk_location,
            os.pardir,
            "icons",
            "nukestudio.png"
        )

        active_project = hiero.ui.activeSequence().project()

        for project in hiero.core.projects():

            # create the session item for the publish hierarchy
            session_item = parent_item.create_item(
                "file.nukestudio",
                "NukeStudio Project",
                project.name(),
                collector=self.plugin
            )
            session_item.set_icon_from_path(icon_path)

            # add the project object to the properties so that the publish
            # plugins know which open project to associate with this item
            session_item.properties.project = project

            self.logger.info(
                "Collected Nuke Studio project: %s" % (project.name(),))

            # enable the active project and expand it. other projects are
            # collapsed and disabled.
            if active_project and active_project.guid() == project.guid():
                session_item.expanded = True
                session_item.checked = True
            elif active_project:
                # there is an active project, but this isn't it. collapse and
                # disable this item
                session_item.expanded = False
                session_item.checked = False

        return session_item


    def collect_node_outputs(self, settings, parent_item):
        """
        Scan known output node types in the session and see if they reference
        files that have been written to disk.

        :param dict settings: Configured settings for this collector
        :param parent_item: The parent item for any write geo nodes collected
        """
        items = []

        publisher = self.parent

        # iterate over all the known output types
        for node_type in _NUKE_OUTPUTS:

            # get all the instances of the node type
            all_nodes_of_type = [n for n in nuke.allNodes()
                if n.Class() == node_type]

            # iterate over each instance
            for node in all_nodes_of_type:

                # Skip the node if its disabled
                if node["disable"].value():
                    continue

                self.logger.info(
                    "Processing %s node: %s" % (node_type, node.name()))

                if node_type == "WriteTank":

                    if not self.__write_node_app:
                        self.logger.error("Unable to process node '%s' without "
                                "the tk-nuke_writenode app!" % node.name())
                        continue

                    # Get the file path and sequence files from the node itself
                    file_path = self.__write_node_app.get_node_render_path(node)
                    thumbnail = self.__write_node_app.generate_node_thumbnail(node)

                else:
                    # evaluate the output path parameter which may include frame
                    # expressions/format
                    param_name = _NUKE_OUTPUTS[node_type]
                    file_path = node[param_name].evaluate()
                    thumbnail = None


                # Collect the item if we have a file_path defined
                if file_path:

                    # Call the parent _collect_file method
                    item = self._collect_file(settings, parent_item, file_path)
                    if not item:
                        continue

                    # the item has been created. update the display name to include
                    # the nuke node to make it clear to the user how it was
                    # collected within the current session. also, prepend nukesession
                    # to the item type so we can process it by the nuke-specific publish
                    item.name = "%s (%s)" % (node.Class(), node.name())

                    # Store a reference to the originating node
                    item.properties.node = node

                    if thumbnail:
                        item.set_thumbnail_from_path(thumbnail)

                    # Add item to the list
                    items.append(item)

        return items


    def _resolve_item_fields(self, item):
        """
        Helper method used to get fields that might not normally be defined in the context.
        Intended to be overridden by DCC-specific subclasses.
        """
        node = item.properties.get("node")
        if node and node.Class() == "WriteTank":
            if self.__write_node_app:
                # Get work_path_template from the write_node app and update fields
                item.properties.work_path_template = \
                    self.__write_node_app.get_node_render_template(node).name
            else:
                self.logger.error("Unable to process item '%s' without "
                        "the tk-nuke_writenode app!" % item.name)

        # If this is a nuke session and we have the workfiles app defined...
        elif item.type == "file.nuke" and self.__workfiles_app:
            # Get work_path_template from the workfiles app for the item's context
            # Note: this needs to happen here instead of during item initialization
            # since the path may change if the context changes
            item.properties.work_path_template = \
                self.__workfiles_app.get_work_template(item.context).name

        # Now run the parent resolve method
        fields = super(NukeSessionCollector, self)._resolve_item_fields(item)

        if node:
            # If not defined, get the height and width from the node
            if "width" not in fields or "height" not in fields:
                fields["width"] = node.width()
                fields["height"] = node.height()

        return fields


    def _get_save_as_action(self):
        """
        Simple helper for returning a log action dict for saving the session
        """
        # default save callback
        callback = nuke.scriptSaveAs

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
    root_name = nuke.root().name()
    return None if root_name == "Root" else root_name

