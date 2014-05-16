# copyright (c) 2014 JP Aumasson <jeanphilippe.aumasson@gmail.com>
#
# This file is part of blueflower.
#
# blueflower is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# blueflower is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with blueflower.  If not, see <http://www.gnu.org/licenses/>.


import getpass
import logging
import os
import re
import signal
import sys


from blueflower import __version__
from blueflower.do import do_file
from blueflower.constants import ENCRYPTED, INFILENAME, PROGRAM, SKIP
from blueflower.types import type_file
from blueflower.utils.log import log_comment, log_encrypted, log_error, \
    log_secret, log_selected, timestamp
from blueflower.utils.hashing import key_derivation, HASH_BYTES


HASHES = frozenset()  # for faster membership testing
HASH_KEY = 0
HASH_REGEX = ''


def get_hashes(hashesfile):
    """gets and checks password, create hashes list"""
    global HASHES
    global HASH_KEY
    global HASH_REGEX
    log_comment('verifying hashes file %s...' % hashesfile)
    pwd = getpass.getpass('password: ')
    fin = open(hashesfile)
    regex = fin.readline().rstrip('\n')
    try:
        (salt, verifier) = fin.readline().rstrip('\n').split(',')
    except ValueError:
        log_comment('failed to extract verifier and salt')
        bye()
    (key, averifier, salt) = key_derivation(pwd, salt)

    fail = False

    if verifier != averifier:
        log_comment('verifier does not match (incorrect password?)')
        fail = True
    else:
        HASH_KEY = key
        HASH_REGEX = regex

    try:
        re.compile(regex)
    except re.error:
        log_comment('invalid regex')
        fail = True

    # file pointer is now at the 3rd line:
    hashes = []
    for line in fin:
        ahash = line.strip()
        # hex string length = 2*HASH_BYTES
        if len(ahash) != 2*HASH_BYTES:
            log_comment('invalid hash length (%d bytes): %s' %
                        (len(ahash), ahash))
            fail = True
        # check that the hash is an hex value
        try:
            int(ahash, 16)
        except ValueError:
            log_comment('invalid hash value (should be hex string): %s'
                        % ahash)
            fail = True
        # only record hashes if we expect to use them
        if not fail:
            hashes.append(ahash)

    # no more failure opportunities
    if fail:
        log_comment('hashes file failed to verify, aborting...')
        bye()

    # record hashes and key, notifies of duplicates
    HASHES = frozenset(hashes)
    log_comment('%d hashes read, %d uniques' % (len(hashes), len(HASHES)))
    log_comment('using regex %s' % HASH_REGEX)
    log_comment('hashes file successfully verified')


def init(path):
    """determinines size and number of files"""
    log_comment('initialization...')
    total_size = 0
    count = 0
    for root, dirs, files in os.walk(path):

        # skip uninteresting places
        for skip in SKIP:
            if skip in dirs:
                dirs.remove(skip)

        for afile in files:
            apath = os.path.join(root, afile)
            count += 1
            try:
                total_size += os.path.getsize(apath)
            except OSError as e:
                log_error(str(e), afile)

    readable = total_size
    for unit in ['bytes', 'KiB', 'MiB', 'GiB', 'TiB']:
        if readable < 1024:
            log_comment('%d files, %3.1f %s' % (count, readable, unit))
            return count
        readable /= 1024.0


def scan(path, count):
    """selects files to process, checks file names"""
    log_comment('scanning files...')
    infilename = re.compile('|'.join(INFILENAME))

    scanned = 0

    # progress bar init
    bar_width = 32
    sys.stdout.write("[%s]" % (" " * (bar_width+1)))
    sys.stdout.flush()
    sys.stdout.write("\b" * (bar_width+2))
    bar_blocksize = count/bar_width
    bar_count = 0

    for root, dirs, files in os.walk(path):

        # skip uninteresting places
        for skip in SKIP:
            if skip in dirs:
                dirs.remove(skip)

        for afile in files:
            abspath = os.path.abspath(os.path.join(root, afile))

            res = infilename.search(afile.lower())
            if res:
                log_secret(res.group(), abspath)

            (ftype, supported) = type_file(abspath)

            if supported:
                if ftype in ENCRYPTED:  # report but do not process
                    log_encrypted(ftype, afile)
                else:
                    do_file(ftype, abspath)
                    scanned += 1
                    bar_count += 1
                    if bar_count >= bar_blocksize:
                        sys.stdout.write("=")
                        sys.stdout.flush()
                        bar_count = 0

    sys.stdout.write("\n")

    log_comment('%d files supported have been processed' % scanned)
    return scanned


def count_secrets(logfile):
    logs = open(logfile).read()
    secrets = logs.count('SECRET,')
    log_comment('%d files or strings flagged as "secret"' % secrets)


def bye():
    print 'thank you for using %s, please report bugs' % PROGRAM
    sys.exit(1)


def usage():
    """prints usage"""
    print 'usage: %s directory [hashes]' % PROGRAM


def banner():
    flower = r"""
        .--'|}         _   ,
       /    /}}  -====;o`\/ }
     .=\.--'`\}        \-'\-'----.
    //` '---./`         \ |-..-'`
    ||  /|              /\/\
     \\| |              `--`
   |\_\\/
   \__/\\
        \\   %s - %s
         \|
    """ % (PROGRAM, __version__)
    print flower


def signal_handler(*_):
    """interrupt upon ^C"""
    sys.stdout.write("\n")
    log_comment('SIGINT received, quitting')
    bye()


def main(args=sys.argv[1:]):
    """main function"""
    if (len(args) < 1):
        usage()
        return 1

    path = args[0]
    if not os.path.exists(path):
        print '%s does not exist' % path
        usage()
        return 1

    hashesfile = ''
    if len(args) > 1:
        hashesfile = args[1]
        if not os.path.exists(hashesfile):
            print '%s does not exist' % hashesfile
            usage()
            return 1

    signal.signal(signal.SIGINT, signal_handler)

    logfile = '%s-%s' % (PROGRAM, timestamp())
    logging.basicConfig(filename=logfile,
                        format='%(message)s',
                        level=logging.INFO)

    banner()
    log_comment('writing to %s' % logfile)

    if hashesfile:
        get_hashes(hashesfile)
    count = init(path)
    scan(path, count)
    count_secrets(logfile)
    bye()
