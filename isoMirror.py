#!/usr/bin/python3

import io, sys, os, re
import subprocess
import tempfile


def checkUser():
    if(os.getuid() != 0):
        print("Run as root")
        sys.exit()

def getInput():
    numArgs = len(sys.argv)
    
    if numArgs < 3:
        scriptName = os.path.basename(__file__)
        print("Usage:")
        print("    ", scriptName, "[ iso(s) ]", "[ mirror dir ]")
        sys.exit()
    else:
        target = sys.argv[-1:]
        images = sys.argv[1:numArgs-1]
        return target, images

def mount(images):
    mountDirs = []
    for iso in images:
        dp = tempfile.TemporaryDirectory()
        status = subprocess.run(["mount", "-o", "ro", iso, dp.name])
        if status.returncode != 0:
            print("Mount failed:", status.returncode, dp.name)
            sys.exit()

        mountDirs.append(dp)
    
    return mountDirs

def rsync(cmd):
    popen = subprocess.Popen(cmd, stdout=subprocess.PIPE, \
            universal_newlines=True)
    for stdoutLine in iter(popen.stdout.readline, ""):
        yield stdoutLine
    popen.stdout.close()
    returnCode = popen.wait()
    if returnCode:
        raise subprocess.CalledProcessError(returnCode, cmd)

def cleanup(mountDirs):
    for d in mountDirs:
        subprocess.run(["umount", d.name])
        d.cleanup()

def main():
    checkUser()
    targetDir, images = getInput()
    mountDirs = mount(images)
#    rsync(["rsync", "-av", ""])

    cleanup(mountDirs)



main()
