# Copyright (c) 2013 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

import sgtk
import re
import os
import glob
import nuke
import random

from sgtk.platform.qt import QtCore, QtGui
from .ui.dialog import Ui_Dialog

logger = sgtk.platform.get_logger(__name__)

settings = sgtk.platform.import_framework("tk-framework-shotgunutils", "settings")

DEFAULT_HEIGHT = 450
DEFAULT_WIDTH = 300


def show_dialog(app_instance):
    """
    Shows the main dialog window
    """
    # In order to handle UIs seamlessly each toolkit enigne has methods for launching
    # different types of windows. By using these methods your windows will be correctly
    # decorated and handled in a consistent fashion by the system

    # We pass the dialog class to this method and leave the actual construction
    # to be carried out by the toolkit
    app_instance.engine.show_dialog("Setup Shot...", app_instance, AppDialog)


class AppDialog(QtGui.QWidget):
    """
    Main application dialog window
    """

    def _get_path_from_template(self, template, name, version, ext, element):
        entity_type = os.environ['ENTITY_TYPE']
        entity_id = int(os.environ['ENTITY_ID'])
        entity = sgtk.sgtk_from_entity(entity_type, entity_id)
        context = entity.context_from_entity(entity_type, entity_id)
        fields = context.as_template_fields(template)
        fields['name'] = name
        fields['version'] = version
        fields['ext'] = ext
        if element != "":
            fields['element'] = element

        return template.apply_fields(fields)

    def _get_fields_from_template(self, template_name, path):
        entity_type = os.environ['ENTITY_TYPE']
        entity_id = int(os.environ['ENTITY_ID'])
        entity = sgtk.sgtk_from_entity(entity_type, entity_id)
        template = entity.templates[template_name % entity_type.lower()]
        return template.get_fields(path)

    def _get_template(self, template_name):
        entity_type = os.environ['ENTITY_TYPE']
        entity_id = int(os.environ['ENTITY_ID'])
        entity = sgtk.sgtk_from_entity(entity_type, entity_id)
        context = entity.context_from_entity(entity_type, entity_id)
        template = entity.templates[template_name % entity_type.lower()]
        return template

    def _nodeClassExists(self, name):
        node_list = []

        def getItem(menu):
            if isinstance(menu, nuke.Menu):
                for item in menu.items():
                    getItem(item)
            else:
                # the menu is actually a command
                if (menu.name() not in node_list):
                    node_list.append(menu.name())

        getItem(nuke.menu("Nodes"))
        return name in node_list


    def __init__(self):
        """
        Constructor
        """
        QtGui.QWidget.__init__(self)

        self.settings_manager = settings.UserSettings(sgtk.platform.current_bundle())
        windowHeight = self.settings_manager.retrieve("window_dimensionsH", DEFAULT_HEIGHT)
        windowWidth = self.settings_manager.retrieve("window_dimensionsW", DEFAULT_WIDTH)

        self.ui = Ui_Dialog()
        self.ui.setupUi(self, windowWidth, windowHeight)

        # App definition for Shotgun requests
        self.app = sgtk.platform.current_bundle()

        self.entityContext = self.app.context.entity

        # These colors come from the bdColors.nk file in /resources
        self.backDropColors = [1833515007, 1433215999, 943285503, 1767926015, 1683365887,
                               711221759, 1281640447, 1680491263, 656877567, 1679696383]

        # Store a list of all SG statuses including ShortCode, Name & BGColor (Hex String)
        self.statusList = self.app.shotgun.find('Status', [['code', 'is_not', '']], ['name', 'bg_color', 'code'])

        # Populate the listbox on the UI with all output types found for the context entity
        self._populateListWidget()

        self.ui.toggleSelectBox.stateChanged.connect(lambda: self._toggleAllItems())

        self.ui.buttonBox.accepted.connect(lambda: self._doImport())
        self.ui.buttonBox.rejected.connect(lambda: self.close())

    def _toggleAllItems(self):
        state = self.ui.toggleSelectBox.checkState()

        for i in range(0, self.ui.listWidget.count()):
            self.ui.listWidget.item(i).setCheckState(state)

    def _populateListWidget(self):
        if self.entityContext is None:
            QtGui.QMessageBox.information(
                self,
                "Error!",
                "Failed to find context for this app to run\n\nTry opening a scene through SG",
            )
            return

        contextID = self.entityContext['id']
        entityType = self.entityContext['type']

        self.theEntity = self.app.shotgun.find_one(entityType, [['id', 'is', contextID]], ['code', 'id'])
        # self.theEntity = self.app.shotgun.find_one(entityType, [['id', 'is', 18144]], ['code', 'id'])

        # Find all published files associated with the Entity the user is in
        # We are only interested in PublishedFiles with a blank element field
        # This filters out all thumbnails and editorial movies
        filters = [
            ['entity', 'is', self.theEntity],
            ['sg_publishing_status', 'is', 'cmpt'],
            ['sg_step_output', 'type_is_not', '']
        ]
        # Store these for later use, no reason to query SG twice
        publishes = self.app.shotgun.find('PublishedFile', filters, ['code', 'sg_step_output', 'sg_publish_path', 'sg_multi_publish', 'sg_element',
                                                                     'version.Version.sg_status_list',
                                                                     'version.Version.sg_is_hero',
                                                                     'version.Version.sg_primary_published_file.PublishedFile.id',
                                                                     'task.Task.step.Step.code'])

        idsToRemove = []  # List of publishes that are to be removed from self.publishes as we've found 'working' replacements
        temp = []
        for i in publishes:
            if i['sg_element'] == 'working':
                # Keep and mark the id of the non-working match
                temp.append(i)
                idsToRemove.append(i['version.Version.sg_primary_published_file.PublishedFile.id'])
            elif i['sg_element'] is None:
                # Keep
                temp.append(i)
            else:
                # Bin
                pass

        # Remove the regular publishes that have working matches
        self.sortedPublishes = []
        for i in temp:
            if i['id'] not in idsToRemove:
                self.sortedPublishes.append(i)

        # Grab all output types that have the 'For_Nuke' field set to True
        taskList = self.app.shotgun.find('Task', [['project', 'is', self.app.context.project]], ['step'])
        stepList = []
        for i in taskList:
            if i['step']:
                if i['step']['name'] not in stepList:
                    stepList.append(i['step']['name'])

        # Formatting for the names
        # Make the first letter capitalized unless the entire word is already capitalized
        self.unformattedSteps = []
        for i in stepList:
            if i.isupper():
                name = i
            else:
                name = i.title()

            item = QtGui.QListWidgetItem()
            item.setCheckState(QtCore.Qt.Checked)
            item.setText(name)
            self.ui.listWidget.addItem(item)

            # Store the un-formatted names in a list for later
            self.unformattedSteps.append(i)

    def _doImport(self):
        """
        Function to find all relevant publishes and import them into Nuke
        """
        # Call a loading widget for the user
        self.app.engine.show_busy('Setup Shot', 'Finding files to import...')

        # Let's find which output types the user doesn't want from the UI
        rejectedTypes = []
        usedTypes = []
        for i in range(self.ui.listWidget.count()):
            if self.ui.listWidget.item(i).checkState() == QtCore.Qt.Unchecked:
                rejectedTypes.append(self.unformattedSteps[i])
            else:
                usedTypes.append(self.unformattedSteps[i])

        # I'm going to start by identifying which publishes are relevant to this entity
        # Then filter down to only the highest version number items
        itemsToImport = self.findItemsToImport(rejectedTypes)

        self.allNodes = []

        # ===========================================================================================
        # The rest of this function is relating to storing node placement in memory to calculate the next nodes
        # position. It is a bit of a mess but it executes quickly.

        # Groupings by type are distinguished by a new backdrop node
        # Groupings by multi-publish entity are placed left to right with new multi-publish entities going below

        # 4 Cases for node position
        #   a - Node is the same multi-publish and output type as the last one
        #       Place at the same Y coords and go along in X

        #   b - Node is the same multi-publish but different output type
        #       This can't happen, because of the list sort in place

        #   c - Node is a different multi-publish and the same output type
        #       Make the X coord the same as the first node in this output type and place below previous node in Y

        #   d - Node is a different multi-publish and different output type
        #       Make the Y coord the origin (first placed node) and X the edgeX (X pos of node furthest to the right)
        # ===========================================================================================

        edgeX = 0  # This variable represents the X coordinate of the current node placed furthest to the right
        originY = 0  # This is the Y coord of the first placed node
        originX = 0  # This is only used for the sticky note 'retime details'

        previousNode = None  # Previously placed node, for retaining X/Y pos info
        previousItem = None  # Previously placed node but actual dictionary info
        for j in usedTypes:
            nodesList = []

            for i in itemsToImport:
                if i['task.Task.step.Step.code'] == j:
                    if i.get('sg_publish_path'):
                        pathToImp = i['sg_publish_path']['local_path']
                        # Simple read node for image / movie file
                        if pathToImp.endswith(('.exr', '.jpg', '.png', '.jpeg', 'cin', '.dpx', '.tiff', '.tif', '.mov', '.mp4', '.psd', '.tga', '.ari', '.gif', '.iff')):
                            node = nuke.createNode("Read")
                            node["file"].fromUserText(pathToImp)

                            statusCode = i['version.Version.sg_status_list']
                            for status in self.statusList:
                                if status['code'] == statusCode:
                                    statusName = status['name']

                                    if status['bg_color']:
                                        colorInt = int('%02x%02x%02x%02x' % (int(status['bg_color'].split(',')[0]),
                                                                             int(status['bg_color'].split(',')[1]),
                                                                             int(status['bg_color'].split(',')[2]), 255), 16)
                                    else:
                                        # Status has no bgColor - 0 is the default node color
                                        colorInt = 0

                                    break
                            else:

                                # Matching status not found - default options - 0 is the default node color
                                statusName = 'Unknown'
                                colorInt = 0

                            node["label"].setValue('SG Status = ' + str(statusName))
                            node["tile_color"].setValue(colorInt)

                            # Find the frame range if it has one
                            seq_range = self._findFrameRange(pathToImp)
                            if seq_range:
                                node["first"].setValue(seq_range[0])
                                node["last"].setValue(seq_range[1])
                            nodesList.append(node)

                            # is a hero element
                            if i['version.Version.sg_is_hero'] == True:
                                node["label"].setValue(node["label"].value()+'\nHERO ELEMENT')
                                # Create the write node

                        # Geometry node setup, going to make a Geometry node and a Camera node here
                        elif pathToImp.endswith(('.abc', '.fbx', '.obj', '.usd')):
                            node = nuke.createNode("ReadGeo2", "file {%s}" % pathToImp)
                            node.setInput(0, None)
                            nodesList.append(node)

                        else:
                            # I don't know what to do with this file type
                            continue

                        # Position / Layout of the nodes
                        if previousNode:
                            if i['sg_multi_publish']['name'] == previousItem['sg_multi_publish']['name']:
                                node.setYpos(previousNode.ypos())
                                node.setXpos(previousNode.xpos() + 250)
                            else:
                                if i['task.Task.step.Step.code'] == previousItem['task.Task.step.Step.code']:
                                    node.setYpos(previousNode.ypos() + 250)
                                    node.setXpos(nodesList[0].xpos())
                                else:
                                    node.setYpos(originY)
                                    node.setXpos(edgeX + 250)
                        else:
                            originX = node.xpos()
                            edgeX = node.xpos()
                            originY = node.ypos()

                        if node.xpos() > edgeX:
                            edgeX = node.xpos()

                        previousNode = node
                        previousItem = i

                        # Create a Camera node underneath the now placed readGeo node
                        if pathToImp.endswith(('.abc', '.fbx', '.obj', '.usd')):
                            camNode = nuke.createNode("Camera2", "read_from_file True file {%s}" % pathToImp)
                            camNode.setInput(0, None)
                            camNode.setXpos(node.xpos())
                            camNode.setYpos(node.ypos() + 50)
                            nodesList.append(camNode)

            self.allNodes += nodesList

            if len(nodesList) > 0:
                # For every loop of J we create a backdrop for the nodes
                for k in nodesList:
                    k['selected'].setValue(True)

                backDrop = self._autoBackdrop()
                if j.isupper():
                    backDrop['label'].setValue(j)
                else:
                    backDrop['label'].setValue(j.title())

                backDrop['name'].setValue('')
                backDrop['note_font_size'].setValue(32)
                backDrop['tile_color'].setValue(random.choice(self.backDropColors))

        # Create a re-time info sticky note
        self.createReTimeStickyNote(originY, originX)

        # Load in the reformat gizmo for MOVs and set basic settings
        self.sortReformats()

        # Sort out the slap comp write nodes
        self.sortSlapWrites()

        # Get rid of the loading widget
        self.app.engine.clear_busy()

        # Close the UI - I doubt the user cares for it anymore
        self.close()

    def _autoBackdrop(self):
        selNodes = nuke.selectedNodes()
        if not selNodes:
            return nuke.nodes.BackdropNode()

        bdX = min([node.xpos() for node in selNodes])
        bdY = min([node.ypos() for node in selNodes])
        bdW = max([node.xpos() + node.screenWidth() for node in selNodes]) - bdX
        bdH = max([node.ypos() + node.screenHeight() for node in selNodes]) - bdY

        zOrder = 0
        selectedBackdropNodes = nuke.selectedNodes("BackdropNode")
        # If there are backdropNodes selected put the new one immediately behind the farthest one
        if len(selectedBackdropNodes):
            zOrder = min([node.knob("z_order").value() for node in selectedBackdropNodes]) - 1
        else:
            # Otherwise (no backdrop in selection) find the nearest backdrop if exists and set the new one in front of it
            nonSelectedBackdropNodes = nuke.allNodes("BackdropNode")
            for nonBackdrop in selNodes:
                for backdrop in nonSelectedBackdropNodes:
                    if self._nodeIsInside(nonBackdrop, backdrop):
                        zOrder = max(zOrder, backdrop.knob("z_order").value() + 1)
                        # Expand the bounds to leave a little border. Elements are offsets for left, top, right and bottom edges respectively
        left, top, right, bottom = (-50, -75, 50, 75)
        bdX += left
        bdY += top
        bdW += (right - left)
        bdH += (bottom - top)

        n = nuke.nodes.BackdropNode(xpos=bdX,
                                    bdwidth=bdW,
                                    ypos=bdY,
                                    bdheight=bdH,
                                    tile_color=int((random.random() * (16 - 10))) + 10,
                                    note_font_size=42,
                                    z_order=zOrder)

        return n

    def _nodeIsInside(self, node, backdropNode):
        """
        Returns true if node geometry is inside backdropNode otherwise returns false
        """
        topLeftNode = [node.xpos(), node.ypos()]
        topLeftBackDrop = [backdropNode.xpos(), backdropNode.ypos()]
        bottomRightNode = [node.xpos() + node.screenWidth(), node.ypos() + node.screenHeight()]
        bottomRightBackdrop = [backdropNode.xpos() + backdropNode.screenWidth(), backdropNode.ypos() + backdropNode.screenHeight()]

        topLeft = (topLeftNode[0] >= topLeftBackDrop[0]) and (topLeftNode[1] >= topLeftBackDrop[1])
        bottomRight = (bottomRightNode[0] <= bottomRightBackdrop[0]) and (bottomRightNode[1] <= bottomRightBackdrop[1])

        return topLeft and bottomRight

    def _findFrameRange(self, path):
        """
        This function was stolen from tk-multi-loader2
        """
        frame_pattern = re.compile(r"([0-9#]+|[%]0\dd)$")
        root, ext = os.path.splitext(path)
        match = re.search(frame_pattern, root)

        if not match:
            return None

        glob_path = "%s%s" % (
            re.sub(frame_pattern, "*", root),
            ext,
        )
        files = glob.glob(glob_path)

        file_roots = [os.path.splitext(f)[0] for f in files]
        frames = [int(re.search(frame_pattern, f).group(1)) for f in file_roots]

        if not frames:
            return None

        if min(frames) == max(frames):
            return None

        return [min(frames), max(frames)]

    def findItemsToImport(self, rejectedTypes):
        # uniqueItems is a double list it contains the items name and the version number immediately next to it
        # This is used for comparison for if higher versions of the same item appear later in the self.sortedPublishes list
        # e.g. ['item1', '23', 'item6', '6']
        uniqueItems = []

        # itemsToImport just contains the base info of the item to import as it comes off the SG query
        itemsToImport = []
        for i in self.sortedPublishes:

            # Not interested in output types that the user doesn't want
            if i['task.Task.step.Step.code'] in rejectedTypes:
                continue

            # Extract version number groups 2 & 3
            match = re.match(r'(.*)(_v)(\d+)(.*)', i['code'])

            if not match:
                if i['code'] not in uniqueItems:
                    uniqueItems.append(i['code'])
                    # Version number 0 for items without a version
                    uniqueItems.append('0')
                    itemsToImport.append(i)

            else:
                versionNumber = match.group(3)
                name = i['code'].replace(match.group(2), "").replace(versionNumber, "")

                if name not in uniqueItems:
                    uniqueItems.append(name)
                    uniqueItems.append(versionNumber)
                    itemsToImport.append(i)

                else:
                    position = uniqueItems.index(name)
                    currentVers = int(uniqueItems[position + 1])

                    if int(versionNumber) > currentVers:
                        uniqueItems.pop(position)
                        uniqueItems.pop(position)
                        uniqueItems.append(name)
                        uniqueItems.append(versionNumber)

                        # We always add 2 values to the uniqueItems list at a time therefore I
                        # can find the index in the itemsToImport list by dividing by 2
                        itemsToImport.pop(int(position / 2))
                        itemsToImport.append(i)

        return itemsToImport

    def createReTimeStickyNote(self, originY, originX):
        if self.theEntity['type'] == 'Shot':
            # Let's requery the Shot and grab more fields
            theShot = self.app.shotgun.find_one('Shot', [['id', 'is', self.theEntity['id']]], ['sg_head_in',
                                                                                               'sg_tail_out',
                                                                                               'sg_cut_in',
                                                                                               'sg_cut_out',
                                                                                               'sg_head_handle',
                                                                                               'sg_tail_handle',
                                                                                               'sg_retime_details'])

            noteMsg = '''Retime Details:%s\n Head In: %s\n Head Handle: %s\n Cut In: %s\n Cut Out: %s\n Tail Handle: %s\n Tail Out: %s\n'''\
                      % (
                         theShot.get('sg_retime_details','None'),
                         theShot.get('sg_head_in','???'),
                         theShot.get('sg_head_handle','???'),
                         theShot.get('sg_cut_in','???'),
                         theShot.get('sg_cut_out','???'),
                         theShot.get('sg_tail_handle', '???'),
                         theShot.get('sg_tail_out','???'),
                         )

            stickyNote = nuke.createNode('StickyNote')
            stickyNote.knob('label').setValue(noteMsg)
            # Green
            stickyNote.knob('tile_color').setValue(16733951)

            stickyNote.setYpos(originY)
            stickyNote.setXpos(originX - 250)

    def sortReformats(self):
        for created_node in self.allNodes:
            if created_node['file'].value().lower()[-4:] in ['.mov', '.mp4']:
                created_node['colorspace'].setValue('Output - Rec.709')
                created_node['frame_mode'].setValue('start at')

                if self._nodeClassExists("HD_to_WorkingRes"):
                    reformat_node = nuke.createNode("HD_to_WorkingRes")
                    reformat_node['label'].setValue('\nNOTICE\nThis is an optional reformat\nthat forces an editorial quicktime\nto look like the working res')
                    reformat_node.setXpos(created_node.xpos())
                    reformat_node.setYpos(created_node.ypos() + 150)
                    reformat_node.setInput(0, created_node)

    def sortSlapWrites(self):
        for created_node in self.allNodes:
            if 'HERO ELEMENT' in created_node['label'].value():
                write_node = nuke.createNode('Write')
                template = self._get_template("nuke_%s_sequence_render")
                path = self._get_path_from_template(template, 'slapcomp', 1, 'exr', '')
                write_node['file'].fromUserText(path)

                write_node.setXpos(created_node.xpos())
                write_node.setYpos(created_node.ypos() + 500)

                # if reformat exists
                if self._nodeClassExists("to_WorkingRes"):
                    working_res_node = nuke.createNode("to_WorkingRes")
                    working_res_node.setXpos(write_node.xpos())
                    working_res_node.setYpos(write_node.ypos() - 150)
                    working_res_node.setInput(0, created_node)
                    write_node.setInput(0, working_res_node)

    def closeEvent(self, event):
        height = self.size().height()
        width = self.size().width()
        self.settings_manager.store("window_dimensionsH", height)
        self.settings_manager.store("window_dimensionsW", width)
