#!/usr/bin/python3

import io, sys, os, re
import subprocess
import tempfile
import pathlib


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
        target = sys.argv[-1]
        images = sys.argv[1:numArgs-1]

        return target, images


## generates random mount dirs in /tmp for ISOs and mounts them
def mount(images):
    mountDirs = []
    for iso in images:
        dp = tempfile.TemporaryDirectory()
        status = subprocess.run(["mount", "-v", "-o", "ro", iso, dp.name])
        if status.returncode != 0:
            print("Mount failed:", status.returncode, dp.name)
            sys.exit()

        mountDirs.append(dp)
    
    return mountDirs


## gets Debian version; assumes all ISOs are same version
def getDebianVersion(mountDirs):
    releaseFile = "/dists/stable/Release"
    version = None
    with open(mountDirs[0].name + releaseFile, "r") as fh:
        for line in fh:
            match = re.match('^Version:\s(\d\d?\.\d\d?)', line.rstrip())
            if match:
                version = match.group(1)
                print("Found Debian", version)
                break
        
        if version == None:
            print("Error finding version")
            fh.close()
            sys.exit()
    
    return version


def rsync(mountDirs, targetDir, debVersion):
    writePath = ''.join([targetDir, debVersion, "/debian"])
    print("Creating", writePath)
    pathlib.Path(writePath).mkdir(parents=True, exist_ok=True)
    
    for image in mountDirs:
        statusDists = subprocess.run(["rsync", "-av", image.name + \
                "/dists", writePath])
        statusPool = subprocess.run(["rsync", "-av", image.name + \
                "/pool", writePath])

        if statusDists.returncode != 0:
            print("Rsync failed:", statusDists.returncode)
        if statusPool.returncode != 0:
            print("Rsync failed:", statusPool.returncode)


def cleanup(mountDirs):
    for d in mountDirs:
        subprocess.run(["umount", "-v", d.name])
        d.cleanup()


def main():
    checkUser()
    targetDir, images = getInput()
    mountDirs = mount(images)
    debVersion = getDebianVersion(mountDirs)
    rsync(mountDirs, targetDir, debVersion)

    cleanup(mountDirs)


main()
