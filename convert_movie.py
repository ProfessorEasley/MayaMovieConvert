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
from collections import namedtuple

FileFormat = namedtuple('FileFormat', ['name', 'extension', 'is_movie'])

VERSION = '1.2'
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

def getConfigPath():
    scriptsDir = os.path.dirname(os.path.realpath(__file__))
    name = os.path.splitext(os.path.basename(__file__))[0] + '.config.json'
    return os.path.join(scriptsDir, name)

def getOutputLogPath():
    scriptsDir = os.path.dirname(os.path.realpath(__file__))
    return os.path.join(scriptsDir, 'ffmpeg_output.txt')

def readSettings():
    cfgPath = getConfigPath()
    if os.path.exists(cfgPath):
        with open(cfgPath, 'r') as f:
            return json.load(f)
    else:
        return dict()

def writeSettings(settings):
    cfgPath = getConfigPath()
    with open(cfgPath, 'w') as f:
        json.dump(settings, f)

def getDefaultOperatingSystem():
    settings = readSettings()
    if 'operatingSystem' in settings:
        return settings['operatingSystem']
    elif cmds.about(windows=True):
        return 'PC'
    else:
        return 'MAC'

def getDefaultFFMpeg(operatingSystem):
    settings = readSettings()
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

def getMovieResolution(ffmpegCommand, inputMoviePath):
    cmd = [ffmpegCommand, '-nostdin', '-y', '-i', inputMoviePath]
    outputFilePath = getOutputLogPath()
    with open(outputFilePath, 'w') as outputFd:
        p = popen(cmd, outputFd, outputFd)
        p.wait()
    with open(outputFilePath, 'r') as fd:
        while True:
            line = fd.readline()
            if len(line) == 0:
                raise Exception('could not determine movie resolution')
            if line.find('Video:') > 0:
                m = re.search('(\\d+)x(\\d+)', re.sub('[^0-9]0x', '', line))
                if not m:
                    raise Exception('failed to determine movie resolution from ffmpeg output')
                return int(m.group(1)), int(m.group(2))

def fileDialogStartDir(currentText, isDir=False):
    if os.path.exists(currentText):
        absPath = os.path.abspath(currentText)
        if isDir:
            return {'startingDirectory': absPath}
        else:
            return {'startingDirectory': os.path.split(absPath)[0]}
    else:
        return dict()

def run():
    global currentMovieSize

    if cmds.window('ConvertMovie', exists=True):
        cmds.deleteUI('ConvertMovie', window=True)

    w = cmds.window('ConvertMovie', width=355, height=400, title='Convert Movie v{}'.format(VERSION), menuBar=True)
    l = cmds.formLayout(parent=w, numberOfDivisions=100)

    def openInstructions(*args):
        cmds.showHelp('https://docs.google.com/document/d/1XVG1hAOgN7OIce_GG3SmsO9xnhpXGswg4ClSeiGN6ao/edit?usp=sharing', absolute=True)

    def openYouTubeTutorial(*args):
        cmds.showHelp('https://www.youtube.com/watch?v=lt_uyIdjtWA', absolute=True)

    def openAbout(*args):
        cmds.confirmDialog(
            title='About', 
            message='Convert Movie Script v{}\nWritten by Sasha Volokh (2022)'.format(VERSION),
            button='OK')

    m = cmds.menu(label='Help', helpMenu=True, parent=w)
    cmds.menuItem(label='Instructions', parent=m, command=openInstructions)
    cmds.menuItem(label='YouTube Tutorial', parent=m, command=openYouTubeTutorial)
    cmds.menuItem(label='About', parent=m, command=openAbout)

    currentMovieSize = None

    def resetMovieSize(*args):
        global currentMovieSize
        inputMoviePath = cmds.textField(inputTextField, q=True, text=True)
        ffmpegCommand = cmds.textField(ffmpegTextField, q=True, text=True)
        if not isValidCommand(ffmpegCommand):
            return
        if len(inputMoviePath) == 0 or not os.path.exists(inputMoviePath):
            return
        try:
            w, h = getMovieResolution(ffmpegCommand, inputMoviePath)
            cmds.text(sourceSizeText, edit=True, label='Source Size: {} px x {} px'.format(w, h))
            cmds.textField(widthTextField, edit=True, text=str(w))
            cmds.textField(heightTextField, edit=True, text=str(h))
            cmds.checkBox(keepProportionsCheckBox, edit=True, enable=True)
            currentMovieSize = (w, h)
        except Exception as e:
            print('failed to get movie resolution: {}'.format(e))
            cmds.text(sourceSizeText, edit=True, label='Source Size: Unknown')
            cmds.textField(widthTextField, edit=True, text='')
            cmds.textField(heightTextField, edit=True, text='')
            cmds.checkBox(keepProportionsCheckBox, edit=True, enable=False)
            currentMovieSize = None

    def checkFFMpeg():
        ffmpegCmd = cmds.textField(ffmpegTextField, q=True, text=True)
        if isValidCommand(ffmpegCmd):
            cmds.textField(ffmpegTextField, edit=True, backgroundColor=(0.0, 0.7, 0.0))
            resetMovieSize()
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
        settings = readSettings()
        operatingSystem = getSelectedOperatingSystem()
        if operatingSystem == 'PC':
            settings['ffmpegCommandPC'] = path
        else:
            settings['ffmpegCommandMAC'] = path
        writeSettings(settings)
        checkFFMpeg()

    def getSelectedOperatingSystem():
        index = cmds.radioButtonGrp(osRadioGroup, q=True, select=True)
        if index == 1:
            return 'PC'
        else:
            return 'MAC'

    def onSelect(operatingSystem):
        def handler(*args):
            settings = readSettings()
            settings['operatingSystem'] = operatingSystem
            writeSettings(settings)
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

    def browseInput(*args):
        currentText = cmds.textField(inputTextField, q=True, text=True)
        filename = cmds.fileDialog2(fileMode=1, caption="Select Movie File", **fileDialogStartDir(currentText))
        if filename is None:
            return
        path = os.path.abspath(filename[0])
        cmds.textField(inputTextField, edit=True, text=path)
        resetMovieSize()

    pathsFrame = cmds.frameLayout(label='Paths', parent=l)

    row = cmds.rowLayout(parent=pathsFrame, numberOfColumns=3, columnWidth3=(90, 190, 50), columnAttach3=('both', 'both', 'both'), adjustableColumn=2)
    cmds.text('Input Movie:', parent=row)
    inputTextField = cmds.textField(parent=row, changeCommand=resetMovieSize)
    browseInputButton = cmds.button(label='Browse', parent=row, command=browseInput)

    def browseOutput(*args):
        currentText = cmds.textField(outputTextField, q=True, text=True)
        filename = cmds.fileDialog2(fileMode=3, caption="Select Output Directory", **fileDialogStartDir(currentText, isDir=True))
        if filename is None:
            return
        path = os.path.abspath(filename[0])
        cmds.textField(outputTextField, edit=True, text=path)

    row = cmds.rowLayout(parent=pathsFrame, numberOfColumns=3, columnWidth3=(90, 190, 50), columnAttach3=('both', 'both', 'both'), adjustableColumn=2)
    cmds.text('Output Directory:', parent=row)
    outputTextField = cmds.textField(parent=row)
    browseOutputButton = cmds.button(label='Browse', parent=row, command=browseOutput)

    def onWidthChanged(*args):
        try:
            w = int(cmds.textField(widthTextField, q=True, text=True))
        except ValueError as e:
            return
        if w % 2 != 0:
            w = int(round(w/2.0))*2
            cmds.textField(widthTextField, edit=True, text=str(w))
        if currentMovieSize and cmds.checkBox(keepProportionsCheckBox, q=True, value=True):
            sourceW, sourceH = currentMovieSize
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
        if currentMovieSize and cmds.checkBox(keepProportionsCheckBox, q=True, value=True):
            sourceW, sourceH = currentMovieSize
            w = int(round((float(sourceW)/sourceH)*h/2.0))*2
            cmds.textField(widthTextField, edit=True, text=str(w))

    outputOptionsFrame = cmds.frameLayout(label='Output Options', collapsable=True, parent=l)
    sourceSizeText = cmds.text('Source Size: Unknown', parent=outputOptionsFrame)
    row = cmds.rowLayout(parent=outputOptionsFrame, numberOfColumns=5, columnWidth5=(50, 50, 50, 50, 120), columnAttach5=('both', 'both', 'both', 'both', 'both'))
    cmds.text('Width:', parent=row)
    widthTextField = cmds.textField(parent=row, changeCommand=onWidthChanged)
    cmds.text('Height: ', parent=row)
    heightTextField = cmds.textField(parent=row, changeCommand=onHeightChanged)
    keepProportionsCheckBox = cmds.checkBox(value=True, label='Keep Proportions', parent=row, changeCommand=onWidthChanged)

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

    def resetUIEnabled():
        cmds.button(convertButton, edit=True, label='Convert', command=convertMovie, parent=l)
        cmds.radioButtonGrp(osRadioGroup, edit=True, enable=True)
        cmds.button(browseFFMpegButton, edit=True, enable=True)
        cmds.button(browseInputButton, edit=True, enable=True)
        cmds.button(browseOutputButton, edit=True, enable=True)
        cmds.textField(inputTextField, edit=True, enable=True)
        cmds.textField(outputTextField, edit=True, enable=True)
        cmds.textField(widthTextField, edit=True, enable=True)
        cmds.textField(heightTextField, edit=True, enable=True)
        cmds.checkBox(keepProportionsCheckBox, edit=True, enable=True)
        cmds.textField(outputFileNameTextField, edit=True, enable=True)
        cmds.optionMenu(numDigitsMenu, edit=True, enable=True)
        cmds.optionMenu(fileFormatMenu, edit=True, enable=True)
        updateUIForFileFormat()

    def endWithSuccess():
        resetUIEnabled()
        cmds.confirmDialog(
                title='Conversion successful', 
                message='The input movie has been successfully converted.',
                button='OK')

    def endWithCancel():
        resetUIEnabled()
        
    def endWithFailure():
        resetUIEnabled()
        cmds.confirmDialog(
                title='Error: Conversion failed', 
                message='The movie conversion failed. Please check the log for more details.',
                button='OK')

    def convertThread(ffmpegCommand, inputMoviePath, outputDir, customSize, outputFileName, frameNumDigits, fileExtension, cancelEvent):
        cmd = [ffmpegCommand, '-nostdin', '-y', '-i', inputMoviePath]
        if customSize:
            cmd += ['-s', str(customSize[0]) + 'x' + str(customSize[1])]
        if fileExtension == 'mp4':
            cmd += ['-c:v', 'libx264', '-c:a', 'aac', '-vf', 'format=yuv420p', '-movflags', '+faststart',
             os.path.join(outputDir, '{}.mp4'.format(outputFileName))]
        elif fileExtension == 'avi':
            cmd += ['-c:v', 'rawvideo', '-pix_fmt', 'yuv420p', os.path.join(outputDir, '{}.avi'.format(outputFileName))]
        else:
            cmd += [os.path.join(outputDir, '{}.%{}d.{}'.format(outputFileName, frameNumDigits, fileExtension))]
        appendToLog('Running command: ' + str(cmd) + '\n')
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

    def parseCustomSize():
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

    def convertMovie(*args):
        global cancelSignal
        ffmpegCommand = cmds.textField(ffmpegTextField, q=True, text=True)
        if not isValidCommand(ffmpegCommand):
            cmds.confirmDialog(
                    title='Error: FFmpeg not found', 
                    message='FFmpeg was not found, please specify the path to the ffmpeg executable',
                    button='OK')
            return
        settings = readSettings()
        inputMoviePath = cmds.textField(inputTextField, q=True, text=True)
        outputDir = cmds.textField(outputTextField, q=True, text=True)
        customSize = parseCustomSize()
        outputFileName = cmds.textField(outputFileNameTextField, q=True, text=True).strip()
        frameNumDigits = cmds.optionMenu(numDigitsMenu, q=True, select=True)
        fileFormat = cmds.optionMenu(fileFormatMenu, q=True, select=True)
        settings['inputMovie'] = inputMoviePath
        settings['outputDirectory'] = outputDir
        settings['customSize'] = customSize
        settings['keepProportions'] = cmds.checkBox(keepProportionsCheckBox, q=True, value=True)
        settings['outputFileName'] = outputFileName
        settings['frameNumDigits'] = frameNumDigits
        settings['fileFormat'] = FILE_FORMATS[fileFormat-1].name
        writeSettings(settings)
        fileFormat = FILE_FORMATS[fileFormat-1].extension
        if len(inputMoviePath) == 0 or len(outputDir) == 0:
            cmds.confirmDialog(
                title='Error: Missing input/output', 
                message='Please specify both the input movie path and the output directory path.',
                button='OK')
            return
        if not os.path.exists(inputMoviePath):
            cmds.confirmDialog(
                title='Error: Invalid input movie path', 
                message='The given input movie path does not exist.',
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
        if customSize is False:
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
        cmds.radioButtonGrp(osRadioGroup, edit=True, enable=False)
        cmds.button(browseFFMpegButton, edit=True, enable=False)
        cmds.button(browseInputButton, edit=True, enable=False)
        cmds.button(browseOutputButton, edit=True, enable=False)
        cmds.textField(inputTextField, edit=True, enable=False)
        cmds.textField(outputTextField, edit=True, enable=False)
        cmds.textField(widthTextField, edit=True, enable=False)
        cmds.textField(heightTextField, edit=True, enable=False)
        cmds.checkBox(keepProportionsCheckBox, edit=True, enable=False)
        cmds.textField(outputFileNameTextField, edit=True, enable=False)
        cmds.optionMenu(numDigitsMenu, edit=True, enable=False)
        cmds.optionMenu(fileFormatMenu, edit=True, enable=False)
        cmds.scrollField(outputLog, edit=True, text='')
        def cancel(*args):
            cancelEvent.set()
        cmds.button(convertButton, edit=True, label='Cancel', command=cancel)
        cancelEvent = threading.Event()
        t = threading.Thread(target=convertThread, 
            args=(ffmpegCommand, inputMoviePath, outputDir, 
                customSize, outputFileName, frameNumDigits, fileFormat, cancelEvent))
        t.start()

    convertButton = cmds.button(label='Convert', command=convertMovie, parent=l)
    cmds.text(label='', parent=l)

    currentSettings = readSettings()
    if 'inputMovie' in currentSettings:
        cmds.textField(inputTextField, edit=True, text=currentSettings['inputMovie'])
    if 'outputDirectory' in currentSettings:
        cmds.textField(outputTextField, edit=True, text=currentSettings['outputDirectory'])
    if 'outputFileName' in currentSettings:
        outputFileName = currentSettings['outputFileName']
        cmds.textField(outputFileNameTextField, edit=True, text=outputFileName)
    if 'frameNumDigits' in currentSettings:
        cmds.optionMenu(numDigitsMenu, edit=True, select=currentSettings['frameNumDigits'])
    if 'fileFormat' in currentSettings:
        try:
            index = list(map(lambda opt: opt.name, FILE_FORMATS)).index(currentSettings['fileFormat'])+1
            cmds.optionMenu(fileFormatMenu, edit=True, select=index)
            updateUIForFileFormat()
        except ValueError:
            pass

    cmds.formLayout(l, edit=True, 
        attachForm=[
            (ffmpegFrame, 'top', 5), 
            (ffmpegFrame, 'left', 5),
            (ffmpegFrame, 'right', 5),
            (pathsFrame, 'left', 5),
            (pathsFrame, 'right', 5),
            (outputOptionsFrame, 'left', 5),
            (outputOptionsFrame, 'right', 5),
            (outputLogFrame, 'left', 5),
            (outputLogFrame, 'right', 5),
            (convertButton, 'bottom', 5),
            (convertButton, 'left', 5),
            (convertButton, 'right', 5)
        ],
        attachControl=[
            (pathsFrame, 'top', 5, ffmpegFrame),
            (outputOptionsFrame, 'top', 5, pathsFrame),
            (outputLogFrame, 'top', 5, outputOptionsFrame)
        ],
        attachPosition=[
            (outputLogFrame, 'bottom', 5, 90),
            (convertButton, 'top', 5, 90)
        ])

    cmds.showWindow(w)
    checkFFMpeg()

    # load these after checking FFMpeg since it will reset the width/height
    if 'customSize' in currentSettings:
        cs = currentSettings['customSize']
        if cs:
            cmds.textField(widthTextField, edit=True, text=str(cs[0]))
            cmds.textField(heightTextField, edit=True, text=str(cs[1]))
    if 'keepProportions' in currentSettings:
        kp = currentSettings['keepProportions']
        cmds.checkBox(keepProportionsCheckBox, edit=True, value=kp)
