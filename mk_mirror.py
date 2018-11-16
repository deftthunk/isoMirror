#!/usr/bin/python3

# Build Debian apt mirror directory out of Debian ISO images.
# Use: mk_mirror ISOFILE [ISOFILE2]... TARGET_DIR
#      mk_mirror -r TARGET_DIR
#
#    -r : fix/sign Release file for existing repo folder

import io, sys, os, re
import subprocess
import tempfile
import pathlib
import distutils.dir_util
import shutil
import gzip
import hashlib
import time

# ==============================
# gpg --fingerprint; last 8 chars
gpg_key_id = '706AD8A2'
# ==============================

def getInput():
    numArgs = len(sys.argv)
    target = ''
    images = ''
    
    if gpg_key_id == '':
        print("> You must first populate 'gpg_key_id' variable with a value")
        sys.exit()

    if numArgs < 3:
        scriptName = os.path.basename(__file__)
        print("Usage:")
        print("    ", scriptName, "[ iso(s) ]", "[ mirror dir ]")
        print("    ", scriptName, "-r ", "[ sub-version ]", "[ mirror dir ]",)
        sys.exit()

    else:
        if sys.argv[1] == '-r':
            # no images, so we need to figure out the path to the Release file
            target = sys.argv[-1]
            version = sys.argv[-2]
            inPath = ""
            releasePath = ""

            # for the existing repo at 'target', we need to find out what the 
            # paths are. for example, in the debian security updates repo:
            # http://site.org/debian-security/dists/stable/updates/Release
            # We need to partition out 'debian-security', and 'stable/updates'
            def findR(target):
                nonlocal inPath
                nonlocal releasePath
                for entry in os.scandir(target):
                    if entry.name == "Release.gpg":
                        if re.match(r'.*' + re.escape(version) + r'/dists/[^/]*stable[^/]*/.*', entry.path):
                            mObj = re.search(r'(/[^/]+/[^/]+/dists)(/.*)/Release', entry.path)
                            inPath = mObj.group(1)
                            releasePath = mObj.group(2)
                    elif entry.is_dir():
                        findR(entry.path)
 

            findR(target)
            return target, None, inPath, releasePath, version

        else:
            target = sys.argv[-1]
            images = sys.argv[1:numArgs-1]

            return target, images, None, None, None


## generates random mount dirs in /tmp for ISOs and mounts them
## returns an array of mounted dirs
def mount(images):
    mountDirs = []
    for iso in images:
        dp = tempfile.TemporaryDirectory()
        status = subprocess.run(["fuseiso", iso, dp.name])
        print("> Mounting", iso, "on", dp.name)
        if status.returncode != 0:
            print("> ERROR: Mount failed:", status.returncode, dp.name)
            cleanup(mountDirs)
            sys.exit()

        mountDirs.append(dp)
    return mountDirs


## gets Debian version; assumes all ISOs are same version and subversion
def getDebianVersion(mountDirs):
    releaseFile = "/dists/stable/Release"
    suite = 'stable'
    if not os.path.exists(mountDirs[0].name + releaseFile):
        releaseFile = '/dists/oldstable/Release'
        suite = 'oldstable'

    version = None
    with open(mountDirs[0].name + releaseFile, "r") as fh:
        for line in fh:
            match = re.match('^Version:\s(\d\d?\.\d\d?)', line.rstrip())
            if match:
                version = match.group(1)
                print("> Found Debian", version)
                break
        
        if version == None:
            print("> ERROR: Problem finding version")
            fh.close()
            sys.exit()
    
    return version, suite


# disables "Acquire-By-Hash" feature and updates the datetime stamp
def fixReleaseHeader(filePath, suite):
    patternHash = 'Acquire-By-Hash: yes'
    newStrHash = 'Acquire-By-Hash: no'
    replaceDate = time.strftime("Date: %a, %d %b %Y %H:%M:%S UTC", time.localtime())
    replaceValid = time.strftime("Valid-Until: %a, %d %b %Y %H:%M:%S UTC", time.localtime(time.time() + 20000000.0))
    replaceSuite = suite
    regexDate = re.compile('^Date:\s(.*)$')
    
    print("replaceValid: ", replaceValid)

    #Create temp file
    fh, abs_path = tempfile.mkstemp()
    with os.fdopen(fh, 'w') as new_file:
        with open(filePath) as old_file:
            for line in old_file:
                if re.match('^Date\:\s', line.rstrip()):
                    newDate = re.sub(r'^(Date:\s).*$', replaceDate, line, 1)
                    new_file.write(newDate)
                elif re.match('^Valid-Until\:\s', line.rstrip()):
                    newValid = re.sub(r'^Valid-Until\:\s(.*)', replaceValid, line, 1)
                    new_file.write(newValid)
                elif re.match('^Suite\:\soldstable', line.rstrip()):
                    newSuite = re.sub(r'^(Suite:\s).*$', replaceSuite, line, 1)
                    new_file.write(newSuite)
                else:
                    new_file.write(line.replace(patternHash, newStrHash))

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
    

def walkDists(srcDists, dstDists, suite):
    # array of symlinks to create later
    defer = []

    for entry in os.scandir(srcDists):
        print("\x1b[2K\r> dists: {}".format(entry.path), end='\r')
        curTargetPath = ''.join([dstDists, '/', entry.name])
        
        if entry.name == 'oldstable':
            curTargetPath = ''.join([dstDists, '/', 'stable'])

        if entry.is_dir() and not entry.is_symlink():
            pathlib.Path(curTargetPath).mkdir(parents=True, exist_ok=True)
            walkDists(entry.path, curTargetPath, suite)

        elif entry.is_file():
            f_name, f_extension = os.path.splitext(entry.name)
            if f_extension == '.gz':
                concatGzip(entry, dstDists)
            else:
                shutil.copy(entry.path, dstDists, follow_symlinks=False)
                os.chmod(curTargetPath, 0o644)
                
                if os.path.basename(curTargetPath) == 'Release':
                    fixReleaseHeader(curTargetPath, 'stable')

        elif entry.is_symlink():
            linkto = os.readlink(entry.path)
            # if prior debian release, fix 'oldstable' to 'stable'
            if entry.name == 'oldstable':
                defer.append(tuple((linkto, 'stable')))
            else:
                defer.append(tuple((linkto, entry.name)))

            continue

        else:
            print("> ERROR: Unknown entry: " + entry.path + entry.name)

    # create symlinks
    for (slink, name) in defer:
        path = ''.join([dstDists, '/', name])
        if not os.path.exists(path):
            os.symlink(slink, path)
 

def walkPool(srcPool, dstPool, suite):
    for entry in os.scandir(srcPool):
        print("\x1b[2K\r> pool: {}".format(entry.name), end='\r')
        
        if entry.is_dir() and not entry.is_symlink():
            curTargetPath = ''.join([dstPool, '/', entry.name])
            pathlib.Path(curTargetPath).mkdir(parents=True, exist_ok=True)
            walkPool(entry.path, curTargetPath, suite)

        elif entry.is_file():
            shutil.copy2(entry.path, dstPool, follow_symlinks=False)


def calcSums(parentDir, algo, fh):
    for entry in os.scandir(parentDir):
        print("\x1b[2K\r> gen checksum: {}".format(entry.path), end='\r')
        if entry.is_dir() and not entry.is_symlink():
            calcSums(entry.path, algo, fh)
        else:
            with open(entry.path, 'rb') as tmp_fh:
                buf = tmp_fh.read()
                if algo == 'md5':
                    fHash = hashlib.md5(buf)
                if algo == 'sha1':
                    fHash = hashlib.sha1(buf)
                if algo == 'sha256':
                    fHash = hashlib.sha256(buf)
                if algo == 'sha512':
                    fHash = hashlib.sha512(buf)

                fSize = os.path.getsize(entry.path)
                print("entry.path: ", entry.path)
                mObj = re.search(r'/stable(?:-[a-zA-z]*)?/(.*)', entry.path)
                path = mObj.group(1)
                
                # right align values
                line = " {:>9} {:>9} {:>9}\n".format(fHash.hexdigest(), \
                        fSize, path)
                fh.write(line)


def calcRelease(distsPath, inPath, releasePath, version):
    print("> Calculating Release file")
    fPath = ''.join([distsPath, releasePath, '/Release'])
    newPath = ''.join([distsPath, releasePath, '/Release.tmp'])

    fixReleaseHeader(fPath, releasePath)

    rel_fh = open(fPath, 'r')
    new_fh = open(newPath, 'w')
    
    # capture header of old Release
    pat = re.compile('^Description\:\s')
    for line in rel_fh:
        new_fh.write(line)
        if pat.match(line):
            break

    # Generate MD5Sum section
    new_fh.write("MD5Sum:\n")
    algo = 'md5'
    calcSums(''.join([distsPath, releasePath, '/main']), algo, new_fh)
    calcSums(''.join([distsPath, releasePath, '/contrib']), algo, new_fh)
    calcSums(''.join([distsPath, releasePath, '/non-free']), algo, new_fh)
    
    # Generate SHA1 section
    new_fh.write("SHA1:\n")
    algo = 'sha1'
    calcSums(''.join([distsPath, releasePath, '/main']), algo, new_fh)
    calcSums(''.join([distsPath, releasePath, '/contrib']), algo, new_fh)
    calcSums(''.join([distsPath, releasePath, '/non-free']), algo, new_fh)

    # Generate SHA256 section
    new_fh.write("SHA256:\n")
    algo = 'sha256'
    calcSums(''.join([distsPath, releasePath, '/main']), algo, new_fh)
    calcSums(''.join([distsPath, releasePath, '/contrib']), algo, new_fh)
    calcSums(''.join([distsPath, releasePath, '/non-free']), algo, new_fh)

    # Generate SHA512 section
    new_fh.write("SHA512:\n")
    algo = 'sha512'
    calcSums(''.join([distsPath, releasePath, '/main']), algo, new_fh)
    calcSums(''.join([distsPath, releasePath, '/contrib']), algo, new_fh)
    calcSums(''.join([distsPath, releasePath, '/non-free']), algo, new_fh)
    
    rel_fh.close()
    new_fh.close()
    
    # Replace old Release file
    os.replace(newPath, fPath)
    
    # Make Release.gpg and InRelease, and remove old copies if they exist
    gpgPath = ''.join([distsPath, releasePath, '/Release.gpg'])
    inReleasePath = ''.join([distsPath, releasePath, '/InRelease'])
    if os.path.exists(gpgPath):
        os.remove(gpgPath)
    if os.path.exists(inReleasePath):
        os.remove(inReleasePath)
    subprocess.run(["gpg", "--armor", "--output", gpgPath, "--detach-sign", fPath])
    subprocess.run(["gpg", "--clearsign", "--output", inReleasePath, fPath])
    print("> Completed Release.gpg, InRelease")
    
    # Make KEY.gpg
    keyPath = ''.join([distsPath, releasePath, '/KEY.gpg'])
    if os.path.exists(keyPath):
        os.remove(keyPath)
    keyId = gpg_key_id
    subprocess.run(["gpg", "--output", keyPath, "--armor", "--export", keyId])


# Build path to write ISO image data to and overwrites empty folder if exists
def buildMirror(mountDirs, targetDir, debVersion, suite):
    writePathRoot = ''.join([targetDir, "/debian/", debVersion])
    print("> Creating ", writePathRoot)
    pathlib.Path(writePathRoot).mkdir(parents=True, exist_ok=True)
    
    #copy files
    for image in mountDirs:
        print("> ISO: {}".format(image.name))
        print("> Copying dists folder")
        walkDists(image.name + "/dists", ''.join([writePathRoot, "/dists"]), suite)
        print("> Copying pool folder")
        print(">")
        walkPool(image.name + "/pool", ''.join([writePathRoot, "/pool"]), suite)

    calcRelease(writePathRoot + "/dists")


def cleanup(mountDirs):
    for d in mountDirs:
        subprocess.run(["fusermount", "-u", d.name])
        d.cleanup()


def main():
    targetDir, images, inPath, releasePath, version = getInput()
    if images == None:
        calcRelease(''.join([targetDir, inPath]), inPath, releasePath, version)
        sys.exit()
    else:
        mountDirs = mount(images)
        debVersion, suite = getDebianVersion(mountDirs)
        buildMirror(mountDirs, targetDir, debVersion, suite)
        cleanup(mountDirs)

main()
