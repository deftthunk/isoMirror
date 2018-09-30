# isoMirror

Create an offline, signed Debian repository file structure from one or more 
Debian DVD/CD ISO images. Intended to be paired with a webserver for hosting.

### Details:

Script will mount and copy ISO image contents to a target directory, creating
the 'dists' and 'pool' folders and their contents. An 'InRelease' and
'Release.gpg' file are also generated using the user's default GPG key.

Requirements:
- Web server for hosting content on network
- Pre-made GPG key pair in user's .gpg folder
- Must add GPG key fingerprint to script (defined variable at top of script)
- Have installed tools 'fuseiso', 'xz', 'gpg', 'fuse', and Python 3.x
- One or more Debian ISOs (tested with Debian 8.x and 9.x) of the same version
- Enough space

### Useage:
./isoMirror /path/to/iso(s) /path/to/target/dir

### Other Considerations
- The newer version of APT in Debian 9.x is more aggressive in ensuring repos
  are secure. A new Debian install will not be able to use this repo since it
  will not recognize the public key used to sign files. You have several
	options:

	Pre-Installation:
    - You can use a Debian preseed file to provide customizations to install
			that aren't available through the normal TUI/GUI. More on that process
    	can be found here:
			https://wiki.debian.org/DebianInstaller/Preseed

		- Alternatively, you can use another script I put together which modifies
    	Debian Net-install ISO images by embedding a preseed file in them so that
			installation can take advantage of a local mirror.
			https://github.com/deftthunk/debNetOffline

	Post-Installation:
    1) Import the GPG public key (after OS installation) by doing the following:
		
			wget -qO - http://server/debian/dists/stable/KEY.gpg | sudo apt-key add -

    2) If for some reason you don't want to (or cannot) use a custom key, 
       Complete installation without a mirror, and then do the following:
    	- open /etc/apt/sources.list
      - find the 'deb' line pointing to your repo (or make it if not present)
        and add '[trusted=yes]' between 'deb' and the hostname, so that it
        looks like this:
      		
					'deb [trusted=yes] http://<ip or name of repo>/debian' ...

      If using Debian 8.x, ignore the above steps and complete the following:
				a) if debian 8.x or prior, ignore steps a & b, and create the empty file
        	/etc/apt/apt.conf.d/99allowunauth
      	b) add the line 'APT::Get::AllowUnauthenticated "true";'

- I haven't done enough testing, but apt may complain after a while if it sees
  the Release file's date is too old. I've seen it happen once, but changing
	it requires resigning several files.
