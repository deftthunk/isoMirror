#!/usr/bin/python3

#
# Build Debian apt mirror directory out of Debian ISO images.
#
# Use: isoMirror ISOFILE [ISOFILE2]... TARGET_DIR
#

import io, sys, os, re
import subprocess
import tempfile
import pathlib
import distutils.dir_util
import shutil
import gzip


#class Dists:
#    def __init__(self, folder):
#        self.name = folder
    

#    def binary_amd64():
        

#    def i18n():
        

#    def debian_installer():
 



def checkUser():
    if(os.getuid() != 0):
        print("Run as root")
        sys.exit()
    else:
        # attempt to find user name
        cwd = os.getcwd().split('/')
        if cwd[0] == 'home':
            user = cwd[1]


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
## returns an array of mounted dirs
def mount(images):
    mountDirs = []
    for iso in images:
        dp = tempfile.TemporaryDirectory()
        status = subprocess.run(["sudo", "-S", "mount", "-v", "-o", "ro", \
                iso, dp.name])
        print("Mounting", iso, "on", dp.name)
        if status.returncode != 0:
            print("Mount failed:", status.returncode, dp.name)
            dp.close()
            cleanup(mountDirs)
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


def concatGzip(entry, writePathRoot):
    tmpFile = ''.join([writePathRoot, '/newtmp'])
    localFile = ''.join([writePathRoot, '/', entry.name])
    
    # open ISO image copy
    with gzip.open(entry.path, 'rb') as f_tmp:
        with open(tmpFile, 'ab') as f_new:
            f_new.write(f_tmp)
    # open local copy (if exists)
    if os.path.exists(localFile):
        with gzip.open(localFile, 'rb') as f_cur:
            with open(tmpFile, 'ab') as f_new:
                f_new.write(f_cur)
    else:
        shutil.move(tmpFile, localFile)

    

def walkDists(parentDir, writePathRoot):
    for entry in os.scandir(parentDir):
        print("entry.path: " + entry.path)
        print("writePathRoot: " + writePathRoot)
        if entry.is_dir() and not entry.is_symlink():
            curTargetPath = ''.join([writePathRoot, '/', entry.name])
            pathlib.Path(curTargetPath).mkdir(parents=True, exist_ok=True)
            walkDists(entry.path, curTargetPath)
            print("leaving")
        elif entry.is_file():
            f_name, f_extension = os.path.splitext(entry.name)
            if f_extension == '.gz':
                concatGzip(entry, writePathRoot)
            else:
                shutil.copy2(entry.path, writePathRoot, follow_symlinks=False)
            

def walkPool(parentDir, writePathRoot):
    for entry in os.scandir(parentDir):
        print(entry)
        if entry.is_dir() and not entry.is_symlink():
            pathlib.path(entry.path).mkdir(parents=True, exist_ok=True)
            walkPool(entry.path, writePathRoot)
#        elif entry.is_symlink():



# Builds path to write ISO image data to and overwrites empty folder if exists
def buildMirror(mountDirs, targetDir, debVersion):
    writePathRoot = ''.join([targetDir, debVersion, "/debian"])
    print("Creating", writePathRoot)
    pathlib.Path(writePathRoot).mkdir(parents=True, exist_ok=True)
    
    # copy dists
    for image in mountDirs:
        walkDists(image.name + "/dists", ''.join([writePathRoot, "/dists"]))
    
    # make symlink ....




def cleanup(mountDirs):
    for d in mountDirs:
        subprocess.run(["umount", "-v", d.name])
        d.cleanup()


def main():
    #checkUser()
    targetDir, images = getInput()
    mountDirs = mount(images)
    debVersion = getDebianVersion(mountDirs)
    buildMirror(mountDirs, targetDir, debVersion)

    cleanup(mountDirs)


main()
