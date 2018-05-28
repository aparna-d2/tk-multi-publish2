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
import pprint
import nuke
import sgtk

HookBaseClass = sgtk.get_hook_baseclass()


class NukeCreateVersionPlugin(HookBaseClass):
    """
    Inherits from CreateVersionPlugin
    """
    ############################################################################
    # protected methods

    def _get_colorspace(self, task_settings, item):
        """
        Get the colorspace for the specified nuke node

        :param node:    The nuke node to find the colorspace for
        :returns:       The string representing the colorspace for the node
        """
        node = item.properties.node

        cs_knob = node.knob("colorspace")
        if not cs_knob:
            return
    
        cs = cs_knob.value()
        # handle default value where cs would be something like: 'default (linear)'
        if cs.startswith("default (") and cs.endswith(")"):
            cs = cs[9:-1]
        return cs


    def _get_frame_range(self, task_settings, item):
        """
        Get the nuke session frame range
        """
        return (int(nuke.root()["first_frame"].value()),
                int(nuke.root()["last_frame"].value()))
