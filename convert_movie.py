'''

Common functions and utilities

2022 Sasha Volokh

Install the script into your Maya script directory, then from within Maya
use the following:

For versions of Maya BEFORE 2022:

import convert_movie
reload(convert_movie)
convert_movie.run()

For versions of Maya 2022 or higher:

import convert_movie
import importlib
importlib.reload(convert_movie)
convert_movie.run()

'''

import maya.cmds as cmds
import maya.utils
import os.path
import time
import threading
import subprocess
import json
import re
import glob
import imghdr
import string
from collections import namedtuple
from functools import partial

FileFormat = namedtuple('FileFormat', ['name', 'extension', 'is_movie'])

VERSION = '2.2'
FILE_FORMATS = [FileFormat('PNG', 'png', False), FileFormat('JPEG', 'jpg', False), FileFormat('MP4', 'mp4', True), FileFormat('AVI', 'avi', True)]

def popen(cmd, stdout, stderr):
    if cmds.about(windows=True):
        CREATE_NO_WINDOW = 0x08000000
        return subprocess.Popen(cmd, stdout=stdout, stderr=stderr, creationflags=CREATE_NO_WINDOW)
    else:
        return subprocess.Popen(cmd, stdout=stdout, stderr=stderr)

def isValidCommand(cmd):
    try:
        with open(os.devnull, 'w') as fnull:
            popen(cmd, stdout=fnull, stderr=fnull)
            return True
    except OSError:
        return False

def getOutputLogPath():
    scriptsDir = os.path.dirname(os.path.realpath(__file__))
    return os.path.join(scriptsDir, 'ffmpeg_output.txt')

def getFFmpegConfigPath():
    scriptsDir = os.path.dirname(os.path.realpath(__file__))
    name = os.path.splitext(os.path.basename(__file__))[0] + '.ffmpeg.json'
    return os.path.join(scriptsDir, name)

def readFFmpegSettings():
    cfgPath = getFFmpegConfigPath()
    if os.path.exists(cfgPath):
        with open(cfgPath, 'r') as f:
            return json.load(f)
    else:
        return dict()

def writeFFmpegSettings(settings):
    cfgPath = getFFmpegConfigPath()
    with open(cfgPath, 'w') as f:
        json.dump(settings, f)

def getDefaultOperatingSystem():
    settings = readFFmpegSettings()
    if 'operatingSystem' in settings:
        return settings['operatingSystem']
    elif cmds.about(windows=True):
        return 'PC'
    else:
        return 'MAC'

def getDefaultFFMpeg(operatingSystem):
    settings = readFFmpegSettings()
    scriptsDir = os.path.dirname(os.path.realpath(__file__))
    if operatingSystem == 'PC':
        defaultCmd = os.path.join(scriptsDir, 'ffmpeg', 'bin', 'ffmpeg.exe')
    else:
        defaultCmd = os.path.join(scriptsDir, 'ffmpeg')
    if operatingSystem == 'PC' and 'ffmpegCommandPC' in settings and isValidCommand(settings['ffmpegCommandPC']):
        return settings['ffmpegCommandPC']
    elif operatingSystem == 'MAC' and 'ffmpegCommandMAC' in settings and isValidCommand(settings['ffmpegCommandMAC']):
        return settings['ffmpegCommandMAC']
    elif isValidCommand('ffmpeg'):
        return 'ffmpeg'
    elif isValidCommand(defaultCmd):
        return defaultCmd
    else:
        if operatingSystem == 'PC' and 'ffmpegCommandPC' in settings:
            return settings['ffmpegCommandPC']
        elif operatingSystem == 'MAC' and 'ffmpegCommandMAC' in settings:
            return settings['ffmpegCommandMAC']
        else:
            return defaultCmd

def getMovieProperties(ffmpegCommand, inputMoviePath):
    cmd = [ffmpegCommand, '-nostdin', '-y', '-ss', '00:00:00', '-to', '00:00:01', '-i', inputMoviePath, '-f', 'null', '-']
    outputFilePath = getOutputLogPath()
    with open(outputFilePath, 'w') as outputFd:
        p = popen(cmd, outputFd, outputFd)
        res = p.wait()
        if res != 0:
            raise Exception('failed to start ffmpeg to determine movie resolution')
    with open(outputFilePath, 'r') as fd:
        lines = fd.read().split('\n')
        size = None
        hasAudioStream = None
        for i in range(len(lines) - 1, 0, -1):
            line = lines[i]
            if size is None and line.find('Video:') > 0:
                m = re.search('(\\d+)x(\\d+)', re.sub('[^0-9]0x', '', line))
                if m:
                    w, h = int(m.group(1)), int(m.group(2))
                    if w % 2 != 0:
                        w = int(round(w/2.0))*2
                    if h % 2 != 0:
                        h = int(round(h/2.0))*2
                    size = w, h 
            if hasAudioStream is None and line.find('Audio:') > 0:
                hasAudioStream = True
            if size is not None and hasAudioStream is not None:
                break
        if size is None:
            raise Exception('could not determine movie resolution')
        if hasAudioStream is None:
            hasAudioStream = False
        return size[0], size[1], hasAudioStream

def fileDialogStartDir(currentText, isDir=False):
    if os.path.exists(currentText):
        absPath = os.path.abspath(currentText)
        if isDir:
            return {'startingDirectory': absPath}
        else:
            return {'startingDirectory': os.path.split(absPath)[0]}
    else:
        return dict()

def getAutoSaveConfigPath():
    scriptsDir = os.path.dirname(os.path.realpath(__file__))
    name = os.path.splitext(os.path.basename(__file__))[0] + '.autosave.json'
    return os.path.join(scriptsDir, name)

def run():
    if cmds.window('ConvertMovie', exists=True):
        cmds.deleteUI('ConvertMovie', window=True)

    w = cmds.window('ConvertMovie', width=380, height=400, title='Convert Movie v{}'.format(VERSION), menuBar=True)
    l = cmds.formLayout(parent=w, numberOfDivisions=100)

    def saveSettings(jsonPath):
        settings = {}
        settings['inputSources'] = [{'input': cmds.textField(source['inputTextField'], q=True, text=True)} for source in sources]
        settings['outputDirectory'] = cmds.textField(outputTextField, q=True, text=True)
        settings['outputSize'] = parseOutputSize()
        settings['keepProportions'] = cmds.checkBox(keepProportionsCheckBox, q=True, value=True)
        settings['outputFileName'] = cmds.textField(outputFileNameTextField, q=True, text=True).strip()
        settings['frameNumDigits'] = cmds.optionMenu(numDigitsMenu, q=True, select=True)
        fileFormat = cmds.optionMenu(fileFormatMenu, q=True, select=True)
        settings['fileFormat'] = FILE_FORMATS[fileFormat-1].name
        with open(jsonPath, 'w') as f:
            json.dump(settings, f)

    def loadSettings(jsonPath):
        settings = dict()
        if os.path.exists(jsonPath):
            try:
                with open(jsonPath, 'r') as f:
                    settings = json.load(f)
            except:
                return False
        if 'inputSources' in settings:
            inputSources = settings['inputSources']
            setNumSources(len(inputSources))
            for sourceIndex in range(len(inputSources)):
                jsonSource = inputSources[sourceIndex]
                source = sources[sourceIndex]
                cmds.textField(source['inputTextField'], edit=True, text=jsonSource['input'])
            if len(sources) > 1:
                for source in sources:
                    cmds.frameLayout(source['frame'], edit=True, collapse=True)
            for source in sources:
                sourceKey = source['key']
                readInputMovieProperties(sourceKey)
                updateSourceTitle(sourceKey)
            updateSourcesLayout()
        if 'outputDirectory' in settings:
            cmds.textField(outputTextField, edit=True, text=settings['outputDirectory'])
        if 'outputFileName' in settings:
            outputFileName = settings['outputFileName']
            cmds.textField(outputFileNameTextField, edit=True, text=outputFileName)
        if 'frameNumDigits' in settings:
            cmds.optionMenu(numDigitsMenu, edit=True, select=settings['frameNumDigits'])
        if 'fileFormat' in settings:
            try:
                index = list(map(lambda opt: opt.name, FILE_FORMATS)).index(settings['fileFormat'])+1
                cmds.optionMenu(fileFormatMenu, edit=True, select=index)
                updateUIForFileFormat()
            except ValueError:
                pass
        if 'outputSize' in settings:
            cs = settings['outputSize']
            if cs:
                cmds.textField(widthTextField, edit=True, text=str(cs[0]))
                cmds.textField(heightTextField, edit=True, text=str(cs[1]))
        if 'keepProportions' in settings:
            kp = settings['keepProportions']
            cmds.checkBox(keepProportionsCheckBox, edit=True, value=kp)
        return True

    def resetSettings():
        setNumSources(0)
        setNumSources(1)
        cmds.textField(outputTextField, edit=True, text='')
        cmds.textField(outputFileNameTextField, edit=True, text='')
        cmds.optionMenu(numDigitsMenu, edit=True, select=4)
        cmds.optionMenu(fileFormatMenu, edit=True, select=1)
        cmds.textField(widthTextField, edit=True, text='')
        cmds.textField(heightTextField, edit=True, text='')
        cmds.checkBox(keepProportionsCheckBox, edit=True, value=True)
        resetOutputMovieSize()

    def onSaveSettings(*args):
        path = cmds.fileDialog2(fileMode=0, caption='Save Settings As..', fileFilter='*.json')
        if not path or len(path) < 1:
            return
        path = path[0]
        saveSettings(path)

    def onLoadSettings(*args):
        path = cmds.fileDialog2(fileMode=1, caption="Select Settings File", fileFilter='*.json')
        if path is None or len(path) < 1:
            return
        path = path[0]
        loadSettings(path)

    def onClearSettings(*args):
        resetSettings()

    def openInstructions(*args):
        cmds.showHelp('https://docs.google.com/document/d/1XVG1hAOgN7OIce_GG3SmsO9xnhpXGswg4ClSeiGN6ao/edit?usp=sharing', absolute=True)

    def openYouTubeTutorial(*args):
        cmds.showHelp('https://www.youtube.com/watch?v=lt_uyIdjtWA', absolute=True)

    def openAbout(*args):
        cmds.confirmDialog(
            title='About', 
            message='Convert Movie Script v{}\nWritten by Sasha Volokh (2022)'.format(VERSION),
            button='OK')

    settingsMenu = cmds.menu(label='Settings', parent=w)
    cmds.menuItem(label='Save As...', parent=settingsMenu, command=onSaveSettings)
    cmds.menuItem(label='Open...', parent=settingsMenu, command=onLoadSettings)
    cmds.menuItem(label='Clear', parent=settingsMenu, command=onClearSettings)

    helpMenu = cmds.menu(label='Help', helpMenu=True, parent=w)
    cmds.menuItem(label='Instructions', parent=helpMenu, command=openInstructions)
    cmds.menuItem(label='YouTube Tutorial', parent=helpMenu, command=openYouTubeTutorial)
    cmds.menuItem(label='About', parent=helpMenu, command=openAbout)

    def getDefaultOutputMovieSize():
        maxWidth = 0
        maxHeight = 0
        for i in range(len(sources)):
            source = sources[i]
            if 'size' in source and source['size'] is not None:
                w, h = source['size']
                maxWidth = max(w, maxWidth)
                maxHeight = max(h, maxHeight)
        if maxWidth == 0 or maxHeight == 0:
            return None
        else:
            return maxWidth, maxHeight

    def resetOutputMovieSize():
        size = getDefaultOutputMovieSize()
        if size is not None:
            cmds.textField(widthTextField, edit=True, text=str(size[0]))
            cmds.textField(heightTextField, edit=True, text=str(size[1]))
            cmds.checkBox(keepProportionsCheckBox, edit=True, enable=True)
        else:
            cmds.textField(widthTextField, edit=True, text='')
            cmds.textField(heightTextField, edit=True, text='')
            cmds.checkBox(keepProportionsCheckBox, edit=True, enable=False)

    def readInputMovieProperties(sourceKey, *args):
        def fail(source):
            cmds.text(source['sourceSizeText'], edit=True, label='Source Size: Unknown')
            source['size'] = None
            source['hasAudioStream'] = None
        global sources
        sourceIndex = findSourceIndex(sourceKey)
        source = sources[sourceIndex]
        inputMoviePath = cmds.textField(source['inputTextField'], q=True, text=True)
        ffmpegCommand = cmds.textField(ffmpegTextField, q=True, text=True)
        source['size'] = None
        if not isValidCommand(ffmpegCommand):
            fail(source)
            return
        if len(inputMoviePath) == 0 or len(glob.glob(inputPathToGlob(inputMoviePath))) == 0:
            fail(source)
            return
        try:
            w, h, hasAudioStream = getMovieProperties(ffmpegCommand, inputMoviePath)
            cmds.text(source['sourceSizeText'], edit=True, label='Source Size: {} px x {} px'.format(w, h))
            cmds.checkBox(keepProportionsCheckBox, edit=True, enable=True)
            source['size'] = w, h
            source['hasAudioStream'] = hasAudioStream
        except Exception as e:
            print('failed to get movie resolution: {}'.format(e))
            fail(source)

    def updateSourceTitle(sourceKey, *args):
        global sources
        sourceIndex = findSourceIndex(sourceKey)
        source = sources[sourceIndex]
        inputMoviePath = cmds.textField(source['inputTextField'], q=True, text=True)
        label = 'Source {}'.format(sourceIndex + 1)
        if len(inputMoviePath) != 0 and len(glob.glob(inputPathToGlob(inputMoviePath))) > 0:
            filename = os.path.basename(inputMoviePath)
            maxFilenameChars = 30
            if len(filename) > maxFilenameChars:
                filename = filename[:maxFilenameChars-3] + '...'
            label += ': {}'.format(filename)
        if 'size' in source and source['size'] is not None:
            w, h = source['size']
            label += ' ({}x{})'.format(w, h)
        cmds.frameLayout(source['frame'], edit=True, label=label)

    def checkFFMpeg():
        ffmpegCmd = cmds.textField(ffmpegTextField, q=True, text=True)
        if isValidCommand(ffmpegCmd):
            cmds.textField(ffmpegTextField, edit=True, backgroundColor=(0.0, 0.7, 0.0))
            for i in range(len(sources)):
                sourceKey = sources[i]['key']
                readInputMovieProperties(sourceKey)
                updateSourceTitle(sourceKey)
            resetOutputMovieSize()
        else:
            cmds.textField(ffmpegTextField, edit=True, backgroundColor=(0.7, 0.0, 0.0))
            cmds.confirmDialog(
                    title='Error: FFmpeg not found', 
                    message='FFmpeg was not found, please specify the path to the ffmpeg executable',
                    button='OK')

    def browseFFMpeg(*args):
        currentText = cmds.textField(ffmpegTextField, q=True, text=True)
        filename = cmds.fileDialog2(fileMode=1, fileFilter='*', caption="Select FFMpeg executable", **fileDialogStartDir(currentText))
        if filename is None:
            return
        path = os.path.abspath(filename[0])
        cmds.textField(ffmpegTextField, edit=True, text=path)
        settings = readFFmpegSettings()
        operatingSystem = getSelectedOperatingSystem()
        if operatingSystem == 'PC':
            settings['ffmpegCommandPC'] = path
        else:
            settings['ffmpegCommandMAC'] = path
        writeFFmpegSettings(settings)
        checkFFMpeg()

    def getSelectedOperatingSystem():
        index = cmds.radioButtonGrp(osRadioGroup, q=True, select=True)
        if index == 1:
            return 'PC'
        else:
            return 'MAC'

    def onSelect(operatingSystem):
        def handler(*args):
            settings = readFFmpegSettings()
            settings['operatingSystem'] = operatingSystem
            writeFFmpegSettings(settings)
            cmds.textField(ffmpegTextField, edit=True, text=getDefaultFFMpeg(operatingSystem))
            checkFFMpeg()
        return handler

    ffmpegFrame = cmds.frameLayout(label='FFMpeg', collapsable=True, parent=l)

    osRadioGroup = cmds.radioButtonGrp(parent=ffmpegFrame, numberOfRadioButtons=2, label='    OS:           ', labelArray2=('PC', 'MAC'), 
        select=1 if getDefaultOperatingSystem() == 'PC' else 2, 
        onCommand1=onSelect('PC'), onCommand2=onSelect('MAC'), columnAlign=(1, 'left'), columnWidth3=(100, 80, 80))
    row = cmds.rowLayout(parent=ffmpegFrame, numberOfColumns=2, columnWidth2=(290, 50), columnAttach2=('both', 'both'), adjustableColumn=1)
    ffmpegTextField = cmds.textField(parent=row, text=getDefaultFFMpeg(getSelectedOperatingSystem()), editable=False)
    browseFFMpegButton = cmds.button(label='Browse', parent=row, command=browseFFMpeg)

    def imagePathToSeqPattern(imgPath):
        numStart = None
        numEnd = None
        for i in range(len(imgPath)-1, -1, -1):
            if imgPath[i] in string.digits:
                numEnd = i + 1
                break
        if numEnd is None:
            return None
        for j in range(numEnd-1, -1, -1):
            if imgPath[j] not in string.digits:
                numStart = j + 1
                break
        if numStart is None:
            numStart = 0
        imageSeqPaths = glob.glob('{}*{}'.format(imgPath[0:numStart], imgPath[numEnd:]))
        anyStartWithZero = False
        if numEnd - numStart > 1:
            for path in imageSeqPaths:
                if path[numStart] == '0':
                    anyStartWithZero = True
                    break
        if anyStartWithZero:
            wildcard = '%{}d'.format(numEnd - numStart)
        else:
            wildcard = '%d'
        return imgPath[0:numStart] + wildcard + imgPath[numEnd:]

    def browseInput(sourceKey, *args):
        sourceIndex = findSourceIndex(sourceKey)
        source = sources[sourceIndex]
        currentText = cmds.textField(source['inputTextField'], q=True, text=True)
        filename = cmds.fileDialog2(fileMode=1, caption="Select Movie or Image Sequence", **fileDialogStartDir(currentText))
        if filename is None:
            return
        path = os.path.abspath(filename[0])
        if imghdr.what(path) is not None:
            patPath = imagePathToSeqPattern(path)
            if patPath is not None:
                path = patPath
        cmds.textField(source['inputTextField'], edit=True, text=path)
        readInputMovieProperties(sourceKey)
        updateSourceTitle(sourceKey)
        resetOutputMovieSize()

    inputOptionsFrame = cmds.frameLayout(label='Input Options', collapsable=True,  parent=l)
    sourcesScroll = cmds.scrollLayout(parent=inputOptionsFrame, height=150, childResizable=True)
    sourcesLayout = cmds.columnLayout(parent=sourcesScroll, columnAttach=('both', 0), rowSpacing=5, adjustableColumn=True)

    global sources
    sources = []
    def findSourceIndex(sourceKey):
        for i in range(len(sources)):
            if sources[i]['key'] == sourceKey:
                return i
        raise Exception('failed to find index of source with key: {}'.format(sourceKey))
    
    def updateSourcesLayout():
        # first move the sources to another layout, then move them in the correct order back to the sources layout
        cmds.button(addSourceButton, edit=True, parent=sourcesScroll)
        for sourceIndex in range(len(sources)):
            source = sources[sourceIndex]
            sourceFrame = source['frame']
            cmds.frameLayout(sourceFrame, edit=True, parent=sourcesScroll)
        for sourceIndex in range(len(sources)):
            source = sources[sourceIndex]
            sourceFrame = source['frame']
            cmds.frameLayout(sourceFrame, edit=True, parent=sourcesLayout)
            updateSourceTitle(source['key'])
            cmds.button(source['moveUpButton'], edit=True, enable=sourceIndex > 0)
            cmds.button(source['moveDownButton'], edit=True, enable=sourceIndex < len(sources) - 1)
            cmds.button(source['deleteButton'], edit=True, enable=len(sources) > 1)
        cmds.button(addSourceButton, edit=True, parent=sourcesLayout)

    def onMoveUp(sourceKey, *args):
        sourceIndex = findSourceIndex(sourceKey)
        if sourceIndex > 0:
            t = sources[sourceIndex-1]
            sources[sourceIndex-1] = sources[sourceIndex]
            sources[sourceIndex] = t
        updateSourcesLayout()

    def onMoveDown(sourceKey, *args):
        sourceIndex = findSourceIndex(sourceKey)
        if sourceIndex < len(sources)-1:
            t = sources[sourceIndex+1]
            sources[sourceIndex+1] = sources[sourceIndex]
            sources[sourceIndex] = t
        updateSourcesLayout()

    def onDelete(sourceKey, *args):
        global sources
        sourceIndex = findSourceIndex(sourceKey)
        cmds.deleteUI(sources[sourceIndex]['frame'])
        sources = sources[:sourceIndex] + sources[sourceIndex+1:]
        updateSourcesLayout()

    def onInputTextFieldChanged(sourceKey, *args):
        readInputMovieProperties(sourceKey)
        updateSourceTitle(sourceKey)
        resetOutputMovieSize()

    def setNumSources(n):
        global sources
        while len(sources) > n:
            lastSource = sources[len(sources) - 1]
            cmds.deleteUI(lastSource['frame'])
            sources = sources[:-1]
        while len(sources) < n:
            sourceNum = len(sources) + 1
            sourceFrame = cmds.frameLayout(label='Source  {}'.format(sourceNum), collapsable=True, backgroundShade=True, marginHeight=5, parent=sourcesLayout)
            sourceKey = sourceFrame # use source frame id as key
            
            row = cmds.rowLayout(parent=sourceFrame, numberOfColumns=3, columnWidth3=(90, 190, 50), columnAttach3=('both', 'both', 'both'), adjustableColumn=2)
            cmds.text('Input Movie:', parent=row)
            inputTextField = cmds.textField(parent=row, changeCommand=partial(onInputTextFieldChanged, sourceKey))
            browseInputButton = cmds.button(label='Browse', parent=row, command=partial(browseInput, sourceKey))

            sourceSizeText = cmds.text('Source Size: Unknown', parent=sourceFrame)

            row = cmds.rowLayout(parent=sourceFrame, numberOfColumns=3, columnWidth3=(110, 100, 100), columnAttach3=('both', 'both', 'both'), adjustableColumn=3)
            moveUpButton = cmds.button('Move Up', parent=row, command=partial(onMoveUp, sourceKey))
            moveDownButton = cmds.button('Move Down', parent=row, command=partial(onMoveDown, sourceKey))
            deleteButton = cmds.button('Delete', parent=row, command=partial(onDelete, sourceKey))
            sources.append({
                'key': sourceKey, 
                'frame': sourceFrame,
                'inputTextField': inputTextField,
                'sourceSizeText': sourceSizeText,
                'browseInputButton': browseInputButton,
                'moveUpButton':  moveUpButton,
                'moveDownButton': moveDownButton,
                'deleteButton': deleteButton
            })
        updateSourcesLayout()

    def onAddSource(*args):
        setNumSources(len(sources) + 1)

    addSourceButton = cmds.button(label='Add Source', parent=sourcesLayout, command=onAddSource)
    setNumSources(1)

    def onWidthChanged(*args):
        try:
            w = int(cmds.textField(widthTextField, q=True, text=True))
        except ValueError as e:
            return
        if w % 2 != 0:
            w = int(round(w/2.0))*2
            cmds.textField(widthTextField, edit=True, text=str(w))
        size = getDefaultOutputMovieSize()
        if size and cmds.checkBox(keepProportionsCheckBox, q=True, value=True):
            sourceW, sourceH = size
            h = int(round((float(sourceH)/sourceW)*w/2.0))*2
            cmds.textField(heightTextField, edit=True, text=str(h))

    def onHeightChanged(*args):
        try:
            h = int(cmds.textField(heightTextField, q=True, text=True))
        except ValueError as e:
            return
        if h % 2 != 0:
            h = int(round(h/2.0))*2
            cmds.textField(heightTextField, edit=True, text=str(h))
        size = getDefaultOutputMovieSize()
        if size and cmds.checkBox(keepProportionsCheckBox, q=True, value=True):
            sourceW, sourceH = size
            w = int(round((float(sourceW)/sourceH)*h/2.0))*2
            cmds.textField(widthTextField, edit=True, text=str(w))

    outputOptionsFrame = cmds.frameLayout(label='Output Options', collapsable=True, parent=l)

    def browseOutput(*args):
        currentText = cmds.textField(outputTextField, q=True, text=True)
        filename = cmds.fileDialog2(fileMode=3, caption="Select Output Directory", **fileDialogStartDir(currentText, isDir=True))
        if filename is None:
            return
        path = os.path.abspath(filename[0])
        cmds.textField(outputTextField, edit=True, text=path)

    row = cmds.rowLayout(parent=outputOptionsFrame, numberOfColumns=3, columnWidth3=(90, 190, 50), columnAttach3=('both', 'both', 'both'), adjustableColumn=2)
    cmds.text('Output Directory:', parent=row)
    outputTextField = cmds.textField(parent=row)
    browseOutputButton = cmds.button(label='Browse', parent=row, command=browseOutput)

    row = cmds.rowLayout(parent=outputOptionsFrame, numberOfColumns=3, columnWidth3=(60, 100, 160), columnAttach3=('both', 'both', 'both'), adjustableColumn=2)
    cmds.text('File Name:', parent=row)
    outputFileNameTextField = cmds.textField(parent=row, text='frame')
    numDigitsMenu = cmds.optionMenu(label='  Frame Digits: ', parent=row)
    cmds.menuItem(label='1')
    cmds.menuItem(label='2')
    cmds.menuItem(label='3')
    cmds.menuItem(label='4')
    cmds.optionMenu(numDigitsMenu, edit=True, select=4)

    def updateUIForFileFormat(*args):
        fmt = FILE_FORMATS[cmds.optionMenu(fileFormatMenu, q=True, select=True)-1]
        cmds.optionMenu(numDigitsMenu, edit=True, enable=not fmt.is_movie)

    fileFormatMenu = cmds.optionMenu(label='File Format:', parent=outputOptionsFrame, changeCommand=updateUIForFileFormat)
    for option in FILE_FORMATS:
        cmds.menuItem(label=option.name)

    row = cmds.rowLayout(parent=outputOptionsFrame, numberOfColumns=5, columnWidth5=(50, 50, 50, 50, 120), width=230, columnAttach5=('both', 'both', 'both', 'both', 'both'))
    cmds.text('Width:', parent=row)
    widthTextField = cmds.textField(parent=row, changeCommand=onWidthChanged)
    cmds.text('Height: ', parent=row)
    heightTextField = cmds.textField(parent=row, changeCommand=onHeightChanged)
    keepProportionsCheckBox = cmds.checkBox(value=True, label='Keep Proportions', parent=row, changeCommand=onWidthChanged)

    outputLogFrame = cmds.frameLayout(label='Output Log', collapsable=True, parent=l)
    outputLog = cmds.scrollField(editable=False, wordWrap=True, parent=outputLogFrame)

    def outputLogSaveAs(*args):
        log = cmds.scrollField(outputLog, q=True, text=True)
        path = cmds.fileDialog2(fileMode=0, caption="Save Output Log As..", fileFilter="*.log")
        if not path or len(path) < 1:
            return
        path = path[0]
        with open(path, 'w') as f:
            f.write(log)

    cmds.popupMenu(parent=outputLogFrame, button=3)
    cmds.menuItem(label='Save As...', command=outputLogSaveAs)

    def appendToLog(msg):
        def fn():
            cmds.scrollField(outputLog, edit=True, insertText=msg, insertionPosition=0)
        maya.utils.executeInMainThreadWithResult(fn)

    def setEditableUIEnabled(enabled):
        if enabled:
            cmds.button(convertButton, edit=True, label='Convert', command=convertMovie, parent=l) # this button becomes a "cancel" button when editing is disabled
        cmds.button(addSourceButton, edit=True, enable=enabled)
        for sourceIndex in range(len(sources)):
            source = sources[sourceIndex]
            cmds.button(source['browseInputButton'], edit=True, enable=enabled)
            cmds.textField(source['inputTextField'], edit=True, enable=enabled)
            cmds.button(source['moveUpButton'], edit=True, enable=enabled)
            cmds.button(source['moveDownButton'], edit=True, enable=enabled)
            cmds.button(source['deleteButton'], edit=True, enable=enabled)
        cmds.radioButtonGrp(osRadioGroup, edit=True, enable=enabled)
        cmds.button(browseFFMpegButton, edit=True, enable=enabled)
        cmds.button(browseOutputButton, edit=True, enable=enabled)
        cmds.textField(outputTextField, edit=True, enable=enabled)
        cmds.textField(widthTextField, edit=True, enable=enabled)
        cmds.textField(heightTextField, edit=True, enable=enabled)
        cmds.checkBox(keepProportionsCheckBox, edit=True, enable=enabled)
        cmds.textField(outputFileNameTextField, edit=True, enable=enabled)
        cmds.optionMenu(numDigitsMenu, edit=True, enable=enabled)
        cmds.optionMenu(fileFormatMenu, edit=True, enable=enabled)
        if enabled:
            updateUIForFileFormat()

    def endWithSuccess():
        setEditableUIEnabled(True)
        cmds.confirmDialog(
                title='Conversion successful', 
                message='The input movie has been successfully converted.',
                button='OK')

    def endWithCancel():
        setEditableUIEnabled(True)
        
    def endWithFailure():
        setEditableUIEnabled(True)
        cmds.confirmDialog(
                title='Error: Conversion failed', 
                message='The movie conversion failed. Please check the log for more details.',
                button='OK')

    def isFileExtensionForMovie(fileExtension):
        for fmt in FILE_FORMATS:
            if fileExtension.lower() == fmt.extension.lower():
                return fmt.is_movie
        raise Exception('unexpected file extension {}'.format(fileExtension))

    def convertThread(ffmpegCommand, inputSources, outputDir, outputSize, outputFileName, frameNumDigits, fileExtension, cancelEvent):
        hasAudioStream = False
        if isFileExtensionForMovie(fileExtension):
            for src in inputSources:
                if src['hasAudioStream']:
                    hasAudioStream = True
                    break
        needNullAudioSrc = False
        if hasAudioStream:
            for src in inputSources:
                if not src['hasAudioStream']:
                    needNullAudioSrc = True
                    break
        cmd = [ffmpegCommand, '-nostdin', '-y']
        for inputSource in inputSources:
            inputMoviePath = inputSource['input']
            cmd += ['-i', inputMoviePath]
        if needNullAudioSrc:
            cmd += ['-f', 'lavfi', '-t', '0.1', '-i', 'anullsrc']
            nullAudioSrcIndex = len(inputSources)
        videoIn = None
        audioIn = None
        filterGraph = []
        if len(inputSources) > 1:
            for srcIndex in range(len(inputSources)):
                filterGraph.append('[{}:v] scale={}:{},setsar=1:1 [vs{}]'.format(srcIndex, outputSize[0], outputSize[1], srcIndex))
            concatFilter = ''
            if hasAudioStream:
                for srcIndex in range(len(inputSources)):
                    audioStreamIndex = srcIndex if inputSources[srcIndex]['hasAudioStream'] else nullAudioSrcIndex
                    concatFilter += '[vs{}] [{}:a] '.format(srcIndex, audioStreamIndex)
            else:
                for srcIndex in range(len(inputSources)):
                    concatFilter += '[vs{}] '.format(srcIndex)
            if hasAudioStream:
                concatFilter += 'concat=n={}:v=1:a=1 [v] [a]'.format(len(inputSources))
                videoIn = 'v'
                audioIn = 'a'
            else:
                concatFilter += 'concat=n={}:v=1:a=0 [v]'.format(len(inputSources))
                videoIn = 'v'
            filterGraph.append(concatFilter)
        else:
            filterGraph.append('[0:v] scale={}:{} [v]'.format(outputSize[0], outputSize[1]))
            videoIn = 'v'
            if hasAudioStream:
                filterGraph.append('[0:a] null [a]')
                audioIn = 'a'
        if fileExtension == 'mp4':
            filterGraph.append('[{}] format=yuv420p [{}]'.format(videoIn, videoIn + 'v'))
            videoIn += 'v'
        cmd += ['-filter_complex', ';'.join(filterGraph)]
        if len(inputSources) > 1:
            cmd += ['-vsync', '2'] # needed to prevent "Frame rate very high for a muxer not efficiently supporting it"
        cmd += ['-map', '[{}]'.format(videoIn)]
        if hasAudioStream:
            cmd += ['-map', '[{}]'.format(audioIn)]
        if fileExtension == 'mp4':
            cmd += ['-c:v', 'libx264', '-c:a', 'aac', '-movflags', '+faststart', os.path.join(outputDir, '{}.mp4'.format(outputFileName))]
        elif fileExtension == 'avi':
            cmd += ['-c:v', 'rawvideo', '-pix_fmt', 'yuv420p', os.path.join(outputDir, '{}.avi'.format(outputFileName))]
        else:
            cmd += [os.path.join(outputDir, '{}.%{}d.{}'.format(outputFileName, frameNumDigits, fileExtension))]
        appendToLog('Running command: ' + cmd[0] + ' ' + ' '.join(['\'{}\''.format(c) for c in cmd[1:]]) + '\n')
        outputFilePath = getOutputLogPath()
        with open(outputFilePath, 'w') as outputFd:
            p = popen(cmd, stdout=outputFd, stderr=outputFd)
            while True:
                if cancelEvent.is_set():
                    maya.utils.executeInMainThreadWithResult(endWithCancel)
                    p.terminate()
                    break
                result = p.poll()
                if result is not None:
                    outputFd.close()
                    with open(outputFilePath, 'r') as fd:
                        logMsg = fd.read()
                        appendToLog(logMsg)
                        if result == 0:
                            maya.utils.executeInMainThreadWithResult(endWithSuccess)
                        else:
                            maya.utils.executeInMainThreadWithResult(endWithFailure)
                        break
                time.sleep(0.1)

    def parseOutputSize():
        widthValue = cmds.textField(widthTextField, q=True, text=True).strip()
        heightValue = cmds.textField(heightTextField, q=True, text=True).strip()
        if len(widthValue) == 0 or len(heightValue) == 0:
            return None
        try:
            w = int(widthValue)
            h = int(heightValue)
        except ValueError:
            return False
        return w, h

    def inputPathToGlob(inputMoviePath):
        for i in range(len(inputMoviePath)):
            if inputMoviePath[i] == '%':
                for j in range(i + 1, len(inputMoviePath)):
                    if inputMoviePath[j] == 'd':
                        return inputMoviePath[0:i] + '*' + inputMoviePath[j+1:]
        return inputMoviePath

    def convertMovie(*args):
        global cancelSignal
        ffmpegCommand = cmds.textField(ffmpegTextField, q=True, text=True)
        if not isValidCommand(ffmpegCommand):
            cmds.confirmDialog(
                    title='Error: FFmpeg not found', 
                    message='FFmpeg was not found, please specify the path to the ffmpeg executable',
                    button='OK')
            return
        inputSources = []
        for sourceIndex in range(len(sources)):
            source = sources[sourceIndex]
            inputMoviePath = cmds.textField(source['inputTextField'], q=True, text=True)
            inputSources.append({'input': inputMoviePath, 'hasAudioStream': bool(source['hasAudioStream'])})
            if len(inputMoviePath) == 0 or len(glob.glob(inputPathToGlob(inputMoviePath))) == 0:
                cmds.confirmDialog(
                    title='Error: Invalid input movie path', 
                    message='The given input movie path does not exist for Source {}.'.format(sourceIndex + 1),
                    button='OK')
                return
        outputDir = cmds.textField(outputTextField, q=True, text=True)
        outputSize = parseOutputSize()
        outputFileName = cmds.textField(outputFileNameTextField, q=True, text=True).strip()
        frameNumDigits = cmds.optionMenu(numDigitsMenu, q=True, select=True)
        fileFormat = cmds.optionMenu(fileFormatMenu, q=True, select=True)
        fileFormat = FILE_FORMATS[fileFormat-1].extension
        if len(outputDir) == 0:
            cmds.confirmDialog(
                title='Error: Missing output directory', 
                message='Please specify the output directory path.',
                button='OK')
            return
        if not os.path.exists(outputDir):
            cmds.confirmDialog(
                title='Error: Invalid output directory path', 
                message='The given output directory path does not exist.',
                button='OK')
            return
        if not os.path.isdir(outputDir):
            cmds.confirmDialog(
                title='Error: Invalid output directory path', 
                message='The file at the given output directory path is not a directory.',
                button='OK')
            return
        if outputSize is False:
            cmds.confirmDialog(
                title='Error: Invalid width/height',
                message='Invalid width/height given, please correct these fields',
                button='OK')
            return
        if len(outputFileName) == 0:
            cmds.confirmDialog(
                title='Error: Missing file name',
                message='Please specify a file name for the output images.',
                button='OK')
            return
        saveSettings(getAutoSaveConfigPath())
        setEditableUIEnabled(False)
        cmds.scrollField(outputLog, edit=True, text='')
        def cancel(*args):
            cancelEvent.set()
        cmds.button(convertButton, edit=True, label='Cancel', command=cancel)
        cancelEvent = threading.Event()
        t = threading.Thread(target=convertThread, 
            args=(ffmpegCommand, inputSources, outputDir, 
                outputSize, outputFileName, frameNumDigits, fileFormat, cancelEvent))
        t.start()

    convertButton = cmds.button(label='Convert', command=convertMovie, parent=l)
    cmds.text(label='', parent=l)

    cmds.formLayout(l, edit=True, 
        attachForm=[
            (ffmpegFrame, 'top', 5), 
            (ffmpegFrame, 'left', 5),
            (ffmpegFrame, 'right', 5),
            (inputOptionsFrame, 'left', 5),
            (inputOptionsFrame, 'right', 5),
            (outputOptionsFrame, 'left', 5),
            (outputOptionsFrame, 'right', 5),
            (outputLogFrame, 'left', 5),
            (outputLogFrame, 'right', 5),
            (convertButton, 'bottom', 5),
            (convertButton, 'left', 5),
            (convertButton, 'right', 5)
        ],
        attachControl=[
            (inputOptionsFrame, 'top', 5, ffmpegFrame),
            (outputOptionsFrame, 'top', 5, inputOptionsFrame),
            (outputLogFrame, 'top', 5, outputOptionsFrame)
        ],
        attachPosition=[
            (outputLogFrame, 'bottom', 5, 90),
            (convertButton, 'top', 5, 90)
        ])

    cmds.showWindow(w)
    checkFFMpeg()

    autoSavePath = getAutoSaveConfigPath()
    if os.path.exists(autoSavePath):
        loadSettings(autoSavePath)