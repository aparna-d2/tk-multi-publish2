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
import maya.cmds as cmds
import maya.mel as mel
import sgtk

HookBaseClass = sgtk.get_hook_baseclass()


class MayaPublishFilesPlugin(HookBaseClass):
    """
    Inherits from PublishFilesPlugin
    """
    @property
    def description(self):
        """
        Verbose, multi-line description of what the plugin does. This can
        contain simple html for formatting.
        """

        desc = super(MayaPublishFilesPlugin, self).description

        return desc + "<br><br>" + """
        After publishing, if a version number is detected in the file, the file
        will automatically be saved to the next incremental version number.
        For example, <code>filename.v001.ext</code> will be published and copied
        to <code>filename.v002.ext</code>

        If the next incremental version of the file already exists on disk, the
        validation step will produce a warning, and a button will be provided in
        the logging output which will allow saving the session to the next
        available version number prior to publishing.

        <br><br><i>NOTE: any amount of version number padding is supported.</i>
        """


    def validate(self, task_settings, item):
        """
        Validates the given item to check that it is ok to publish. Returns a
        boolean to indicate validity.

        :param task_settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process
        :returns: True if item is valid, False otherwise.
        """
        publisher = self.parent
        path = item.properties.path

        if item.type == 'file.maya':

            # if the file has a version number in it, see if the next version exists
            next_version_path = publisher.util.get_next_version_path(path)
            if next_version_path and os.path.exists(next_version_path):

                # determine the next available version_number. just keep asking for
                # the next one until we get one that doesn't exist.
                while os.path.exists(next_version_path):
                    next_version_path = publisher.util.get_next_version_path(
                        next_version_path)

                # now extract the version number of the next available to display
                # to the user
                version = publisher.util.get_version_number(next_version_path)

                self.logger.error(
                    "The next version of this file already exists on disk.",
                    extra={
                        "action_button": {
                            "label": "Save to v%s" % (version,),
                            "tooltip": "Save to the next available version number, "
                                       "v%s" % (version,),
                            "callback": lambda: _save_session(next_version_path)
                        }
                    }
                )
                return False

        return super(MayaPublishFilesPlugin, self).validate(task_settings, item)


    def publish(self, task_settings, item):
        """
        Executes the publish logic for the given item and settings.

        :param task_settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process
        """
        path = item.properties.path

        # ensure the session is saved
        if item.type == 'file.maya':
            _save_session(sgtk.util.ShotgunPath.normalize(path))

            # Store any file dependencies
            item.properties.publish_dependencies = _get_scene_dependencies()

        super(MayaPublishFilesPlugin, self).publish(task_settings, item)


    def finalize(self, task_settings, item):
        """
        Execute the finalization pass. This pass executes once all the publish
        tasks have completed, and can for example be used to version up files.

        :param task_settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process
        """
        path = item.properties.path

        super(MayaPublishFilesPlugin, self).finalize(task_settings, item)

        # only version up the file if the publish went through successfully.
        if item.properties.get("sg_publish_data"):
            # insert the path into the properties
            if item.type == 'file.maya':
                item.properties.next_version_path = self._bump_file_version(path)


    def _bump_file_version(self, path):
        """
        Save the supplied path to the next version on disk.
        """

        publisher = self.parent
        path = sgtk.util.ShotgunPath.normalize(path)
        version_number = publisher.util.get_version_number(path)

        if version_number is None:
            self.logger.debug(
                "No version number detected in the file path. "
                "Skipping the bump file version step."
            )
            return None

        self.logger.info("Incrementing session file version number...")

        next_version_path = publisher.util.get_next_version_path(path)

        # nothing to do if the next version path can't be determined or if it
        # already exists.
        if not next_version_path:
            self.logger.warning("Could not determine the next version path.")
            return None
        elif os.path.exists(next_version_path):
            self.logger.warning(
                "The next version of the path already exists",
                extra={
                    "action_show_folder": {
                        "path": next_version_path
                    }
                }
            )
            return None

        # save the session to the new path
        _save_session(next_version_path)
        self.logger.info("Session saved as: %s" % (next_version_path,))

        return next_version_path


def _get_scene_dependencies():
    """
    Find additional dependencies from the scene
    """

    # default implementation looks for references and
    # textures (file nodes) and returns any paths that
    # match a template defined in the configuration
    ref_paths = set()

    # first let's look at maya references
    ref_nodes = cmds.ls(references=True)
    for ref_node in ref_nodes:
        # get the path:
        ref_path = cmds.referenceQuery(ref_node, filename=True)
        # make it platform dependent
        # (maya uses C:/style/paths)
        ref_path = ref_path.replace("/", os.path.sep)
        if ref_path:
            ref_paths.add(ref_path)

    # now look at file texture nodes
    for file_node in cmds.ls(l=True, type="file"):
        # ensure this is actually part of this session and not referenced
        if cmds.referenceQuery(file_node, isNodeReferenced=True):
            # this is embedded in another reference, so don't include it in
            # the breakdown
            continue

        # get path and make it platform dependent
        # (maya uses C:/style/paths)
        texture_path = cmds.getAttr(
            "%s.fileTextureName" % file_node).replace("/", os.path.sep)
        if texture_path:
            ref_paths.add(texture_path)

    return list(ref_paths)


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
