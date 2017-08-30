# -*- coding: utf-8 -*-

# Copyright (C) 2004, 2005, 2006, 2007, 2008, 2009, 2010, 2011, 2012
#               Canonical Ltd.
#
# This file is part of Germinate.
#
# Germinate is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation; either version 2, or (at your option) any
# later version.
#
# Germinate is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Germinate; see the file COPYING.  If not, write to the Free
# Software Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA
# 02110-1301, USA.

import logging
import optparse
import subprocess
import sys

import germinate.archive
import germinate.defaults
from germinate.germinator import Germinator
from germinate.log import germinate_logging
from germinate.seeds import SeedError, SeedStructure
import germinate.version


MIRRORS = [germinate.defaults.mirror]
COMPONENTS = ["main"]


class Package:
    def __init__(self, name):
        self.name = name
        self.seed = {}
        self.installed = 0

    def set_seed(self, seed):
        self.seed[seed] = 1

    def set_installed(self):
        self.installed = 1

    def output(self, outmode):
        ret = self.name.ljust(30) + "\t"
        if outmode == "i":
            if self.installed and not len(self.seed):
                ret += "deinstall"
            elif not self.installed and len(self.seed):
                ret += "install"
            else:
                return ""
        elif outmode == "r":
            if self.installed and not len(self.seed):
                ret += "install"
            elif not self.installed and len(self.seed):
                ret += "deinstall"
            else:
                return ""
        else:           # default case
            if self.installed and not len(self.seed):
                ret = "- " + ret
            elif not self.installed and len(self.seed):
                ret = "+ " + ret
            else:
                ret = "  " + ret
            ret += ",".join(sorted(self.seed))
        return ret


class Globals:
    def __init__(self):
        self.package = {}
        self.seeds = []
        self.outputs = {}
        self.outmode = ""

    def set_seeds(self, options, seeds):
        self.seeds = seeds

        # Suppress most log information
        germinate_logging(logging.CRITICAL)
        logging.getLogger('germinate.archive').setLevel(logging.INFO)

        global MIRRORS, COMPONENTS
        print("Germinating")
        g = Germinator(options.arch)

        archive = germinate.archive.TagFile(
            options.dist, COMPONENTS, options.arch, MIRRORS, cleanup=True)
        g.parse_archive(archive)

        needed_seeds = []
        build_tree = False
        try:
            structure = SeedStructure(options.release, options.seeds)
            for seedname in self.seeds:
                if seedname == ('%s+build-depends' % structure.supported):
                    seedname = structure.supported
                    build_tree = True
                needed_seeds.append(seedname)
            g.plant_seeds(structure, seeds=needed_seeds)
        except SeedError:
            sys.exit(1)
        g.grow(structure)

        for seedname in structure.names:
            for pkg in g.get_seed_entries(structure, seedname):
                self.package.setdefault(pkg, Package(pkg))
                self.package[pkg].set_seed(seedname + ".seed")
            for pkg in g.get_seed_recommends_entries(structure, seedname):
                self.package.setdefault(pkg, Package(pkg))
                self.package[pkg].set_seed(seedname + ".seed-recommends")
            for pkg in g.get_depends(structure, seedname):
                self.package.setdefault(pkg, Package(pkg))
                self.package[pkg].set_seed(seedname + ".depends")

            if build_tree:
                build_depends = set(g.get_build_depends(structure, seedname))
                for inner in structure.inner_seeds(structure.supported):
                    build_depends -= set(g.get_seed_entries(structure, inner))
                    build_depends -= set(g.get_seed_recommends_entries(
                        structure, inner))
                    build_depends -= g.get_depends(structure, inner)
                for pkg in build_depends:
                    self.package.setdefault(pkg, Package(pkg))
                    self.package[pkg].set_seed(structure.supported +
                                               ".build-depends")

    def parse_dpkg(self, fname):
        if fname is None:
            dpkg_cmd = subprocess.Popen(['dpkg', '--get-selections'],
                                        stdout=subprocess.PIPE,
                                        universal_newlines=True)
            try:
                lines = dpkg_cmd.stdout.readlines()
            finally:
                if dpkg_cmd.stdout:
                    dpkg_cmd.stdout.close()
                dpkg_cmd.wait()
        else:
            with open(fname) as f:
                lines = f.readlines()
        for l in lines:
            pkg, st = l.split(None)
            self.package.setdefault(pkg, Package(pkg))
            if st == "install" or st == "hold":
                self.package[pkg].set_installed()

    def set_output(self, mode):
        self.outmode = mode

    def output(self):
        for k in sorted(self.package):
            l = self.package[k].output(self.outmode)
            if len(l):
                print(l)


def parse_options(argv):
    epilog = '''\
A list of seeds against which to compare may be supplied as non-option
arguments.  Seeds from which they inherit will be added automatically.  The
default is 'desktop'.'''

    parser = optparse.OptionParser(
        prog='germinate-pkg-diff',
        usage='%prog [options] [seeds]',
        version='%prog ' + germinate.version.VERSION,
        epilog=epilog)
    parser.add_option('-l', '--list', dest='dpkg_file', metavar='FILE',
                      help='read list of packages from this file '
                           '(default: read from dpkg --get-selections)')
    parser.add_option('-m', '--mode', dest='mode', type='choice',
                      choices=('i', 'r', 'd'), default='d', metavar='[i|r|d]',
                      help='show packages to install/remove/diff (default: d)')
    parser.add_option('-S', '--seed-source', dest='seeds', metavar='SOURCE',
                      default=germinate.defaults.seeds,
                      help='fetch seeds from SOURCE (default: %s)' %
                           germinate.defaults.seeds)
    parser.add_option('-s', '--seed-dist', dest='release', metavar='DIST',
                      default=germinate.defaults.release,
                      help='fetch seeds for distribution DIST '
                           '(default: %default)')
    parser.add_option('-d', '--dist', dest='dist',
                      default=germinate.defaults.dist,
                      help='operate on distribution DIST (default: %default)')
    parser.add_option('-a', '--arch', dest='arch',
                      default=germinate.defaults.arch,
                      help='operate on architecture ARCH (default: %default)')

    options, args = parser.parse_args(argv[1:])

    options.seeds = options.seeds.split(',')
    options.dist = options.dist.split(',')

    return options, args


def main(argv):
    g = Globals()

    options, args = parse_options(argv)

    g.set_output(options.mode)
    g.parse_dpkg(options.dpkg_file)
    if not len(args):
        args = ["desktop"]
    g.set_seeds(options, args)
    g.output()

    return 0
