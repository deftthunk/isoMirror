#!/usr/bin/python3

# Build Debian apt mirror directory out of Debian ISO images.
# Use: isoMirror ISOFILE [ISOFILE2]... TARGET_DIR

import io, sys, os, re
import subprocess
import tempfile
import pathlib
import distutils.dir_util
import shutil
import gzip
import hashlib


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
        status = subprocess.run(["fuseiso", iso, dp.name])
        print(">> Mounting", iso, "on", dp.name)
        if status.returncode != 0:
            print("Err: Mount failed:", status.returncode, dp.name)
            dp.close()
            cleanup(mountDirs)
            sys.exit()

        mountDirs.append(dp)
    
    return mountDirs


## gets Debian version; assumes all ISOs are same version and subversion
def getDebianVersion(mountDirs):
    releaseFile = "/dists/stable/Release"
    version = None
    with open(mountDirs[0].name + releaseFile, "r") as fh:
        for line in fh:
            match = re.match('^Version:\s(\d\d?\.\d\d?)', line.rstrip())
            if match:
                version = match.group(1)
                print(">> Found Debian", version)
                break
        
        if version == None:
            print("Err: Problem finding version")
            fh.close()
            sys.exit()
    
    return version


# disables "Acquire-By-Hash" feature and updates the datetime stamp
def fixReleaseHeader(filePath):
    patternHash = 'Acquire-By-Hash: yes'
    patternDate = 'Date: Sat, 09 Dec 2017 09:16:24 UTC'
    newStrHash = 'Acquire-By-Hash: no'
    newStrDate = 'Date: Sat, 09 Dec 2020 09:16:24 UTC'
    
    #Create temp file
    fh, abs_path = tempfile.mkstemp()
    with os.fdopen(fh, 'w') as new_file:
        with open(filePath) as old_file:
            for line in old_file:
#                print("DEBUG: " + line)
                new_file.write(line.replace(patternHash, newStrHash))
                new_file.write(line.replace(patternDate, newStrDate))
                
    #Replace orig file with new
    os.remove(filePath)
    shutil.move(abs_path, filePath)


def concatGzip(entry, writePathRoot):
    tmpFile = ''.join([writePathRoot, '/newtmp'])
    localFile = ''.join([writePathRoot, '/', entry.name])

    # if gzip file already exists
    if os.path.exists(localFile):
        with gzip.GzipFile(localFile, 'rb') as f_cur:
            with open(tmpFile, 'ab') as f_new:
                f_new.write(f_cur.read())
    
                # open ISO image copy
                with gzip.GzipFile(entry.path, 'rb') as data:
                    f_new.write(data.read())

    # create new file
    else:
        with gzip.GzipFile(entry.path, 'rb') as data:
            with open(tmpFile, 'ab') as f_new:
                f_new.write(data.read())

    # zip up whatever's left
    with open(tmpFile, 'rb') as f_in:
        with gzip.GzipFile(localFile, 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)

    if os.path.basename(localFile) == 'Packages.gz':
        newPackage = ''.join([writePathRoot, '/Packages'])
        newPackageXz = ''.join([writePathRoot, '/Packages.xz'])
        if os.path.exists(newPackageXz):
            os.remove(newPackageXz)

        os.replace(tmpFile, newPackage)
        subprocess.run(["xz", "-zk", newPackage])
    else:
        os.remove(tmpFile)
    

def walkDists(parentDir, writePathRoot):
    # array of symlinks to create later
    defer = []

    for entry in os.scandir(parentDir):
        print("> wd: entry.path: " + entry.path)
        curTargetPath = ''.join([writePathRoot, '/', entry.name])

        if entry.is_dir() and not entry.is_symlink():
            pathlib.Path(curTargetPath).mkdir(parents=True, exist_ok=True)
            walkDists(entry.path, curTargetPath)
#            print("> wd: leaving")

        elif entry.is_file():
            f_name, f_extension = os.path.splitext(entry.name)
            if f_extension == '.gz':
#                print("> wd: gzip: " + entry.name)
                concatGzip(entry, writePathRoot)
            else:
#                print("wd file copy")
                shutil.copy(entry.path, writePathRoot, follow_symlinks=False)
                os.chmod(curTargetPath, 0o644)
                
                if os.path.basename(curTargetPath) == 'Release':
#                    print("wd Release header")
                    fixReleaseHeader(curTargetPath)

        elif entry.is_symlink():
#            print("wd symlink")
            linkto = os.readlink(entry.path)
            defer.append(tuple((linkto, entry.name)))
            continue

        else:
            print("wd: Err: Unknown entry: " + entry.path + entry.name)

    # create symlinks
    for (slink, name) in defer:
        path = ''.join([writePathRoot, '/', name])
        if not os.path.exists(path):
            os.symlink(slink, path)
 

def walkPool(parentDir, writePathRoot):
    for entry in os.scandir(parentDir):
        print("> wp: Writing file: " + entry.name)
        
        if entry.is_dir() and not entry.is_symlink():
            curTargetPath = ''.join([writePathRoot, '/', entry.name])
            pathlib.Path(curTargetPath).mkdir(parents=True, exist_ok=True)
            walkPool(entry.path, curTargetPath)
#            print("> wp: leaving")

        elif entry.is_file():
            shutil.copy2(entry.path, writePathRoot, follow_symlinks=False)


def calcSums(parentDir, fHash, fh):
    for entry in os.scandir(parentDir):
        print("> cs: entry.path: " + entry.path)
        if entry.is_dir() and not entry.is_symlink():
            calcSums(entry.path, fHash, fh)
        else:
            with open(entry.path, 'rb') as tmp_fh:
                buf = tmp_fh.read()
                fHash.update(buf)
                fSize = os.path.getsize(entry.path)
                mObj = re.search(r'\/stable\/(.*)', entry.path)
                path = mObj.group(1)
                
                line = " {:>9} {:>9} {:>9}\n".format(fHash.hexdigest(), fSize, path)
                fh.write(line)


def calcRelease(distsPath):
    print(">> starting calcRelease")
    fPath = ''.join([distsPath, '/stable', '/Release'])
    newPath = ''.join([distsPath, '/stable', '/Release.tmp'])
    rel_fh = open(fPath, 'r')
    new_fh = open(newPath, 'w')
    
    # capture header of old Release
#    print(">> writing header")
    pat = re.compile('^Description\:\s')
    for line in rel_fh:
        new_fh.write(line)
        if pat.match(line):
            break

    # Generate MD5Sum section
    new_fh.write("MD5Sum:\n")
    fHash = hashlib.md5()
    calcSums(''.join([distsPath, '/stable/main']), fHash, new_fh)
    calcSums(''.join([distsPath, '/stable/contrib']), fHash, new_fh)
    
    # Generate SHA1 section
    new_fh.write("SHA1:\n")
    fHash = hashlib.sha1()
    calcSums(''.join([distsPath, '/stable/main']), fHash, new_fh)
    calcSums(''.join([distsPath, '/stable/contrib']), fHash, new_fh)

    # Generate SHA256 section
    new_fh.write("SHA256:\n")
    fHash = hashlib.sha256()
    calcSums(''.join([distsPath, '/stable/main']), fHash, new_fh)
    calcSums(''.join([distsPath, '/stable/contrib']), fHash, new_fh)

    # Generate SHA512 section
    new_fh.write("SHA512:\n")
    fHash = hashlib.sha512()
    calcSums(''.join([distsPath, '/stable/main']), fHash, new_fh)
    calcSums(''.join([distsPath, '/stable/contrib']), fHash, new_fh)
    
    print("Closing release handles")
    rel_fh.close()
    new_fh.close()
    
    # Replace old Release file
    os.replace(newPath, fPath)
    
    # Make Release.gpg
    gpgPath = ''.join([distsPath, '/stable', '/Release.gpg'])
    inReleasePath = ''.join([distsPath, '/stable', '/InRelease'])
    subprocess.run(["gpg", "--armor", "--output", gpgPath, "--detach-sign", fPath])
    subprocess.run(["gpg", "--clearsign", "--output", inReleasePath, fPath])
    print("GPG and InRelease done")
    
    # Make KEY.gpg
    keyPath = ''.join([distsPath, '/stable', '/KEY.gpg'])
    keyId = 'FDE53A2826658E4B'
    subprocess.run(["gpg", "--output", keyPath, "--armor", "--export", keyId])


# Builds path to write ISO image data to and overwrites empty folder if exists
def buildMirror(mountDirs, targetDir, debVersion):
    writePathRoot = ''.join([targetDir, debVersion, "/debian"])
    print("Creating", writePathRoot)
    pathlib.Path(writePathRoot).mkdir(parents=True, exist_ok=True)
    
    #copy files
    for image in mountDirs:
        walkDists(image.name + "/dists", ''.join([writePathRoot, "/dists"]))
        walkPool(image.name + "/pool", ''.join([writePathRoot, "/pool"]))

    calcRelease(writePathRoot + "/dists")


def cleanup(mountDirs):
    for d in mountDirs:
        subprocess.run(["fusermount", "-u", d.name])
        d.cleanup()


def main():
    targetDir, images = getInput()
    mountDirs = mount(images)
    debVersion = getDebianVersion(mountDirs)
    buildMirror(mountDirs, targetDir, debVersion)
    cleanup(mountDirs)


main()
