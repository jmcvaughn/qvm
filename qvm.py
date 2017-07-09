#!/usr/bin/env python2

# Standard library
from __future__ import print_function
from math import ceil
from random import randrange
from types import *
import errno
import os
import subprocess
import sys

# Extra packages
import libzfs_core
import yaml

# Custom modules
import zfs_cli


# error_print(): prints error message with a prefix to STDERR
def error_print(error_prefix, message):
    print(error_prefix + message, file=sys.stderr)


# import_yaml(): takes file path string argument, validates and returns
# a dictionary containing all qvm dictionaries
def import_yaml(vm_file):
    error_prefix = 'Error importing {}: '.format(vm_file)

    # Check if vm_file exists
    if os.path.exists(vm_file) is False:
        error_print(error_prefix, 'file not found')
        return 1

    # Import and validate YAML document, raise exception if error
    # Read as stream as PyYAML will provide more detailed error reports
    yamldoc = yaml.load_all(open(vm_file).read())

    # Initialise dictionaries
    userdata = None
    metadata = None
    vm = None

    # Load all YAML documents in yamldoc into Python dictionaries,
    # deleting qvm identifer keys. Print error if document specifier missing.
    for document in yamldoc:
        if 'qvm' not in document:
            error_print(
                error_prefix,
                'missing user-data, meta-data or vm specifier in document'
            )
            return 1
        elif document['qvm'] == 'user-data':
            userdata = document
            del userdata['qvm']
        elif document['qvm'] == 'meta-data':
            metadata = document
            del metadata['qvm']
        elif document['qvm'] == 'vm':
            vm = document
            del vm['qvm']

    # Print error if document missing
    if (userdata is None) or (metadata is None) or (vm is None):
        error_print(
            error_prefix, 'missing user-data, meta-data or vm document'
        )
        return 1

    # Print error if disk dictionary missing from self.vm
    if 'disk' not in vm:
        error_print(
            error_prefix, 'missing disk dictionary in vm document '
            + '(can contain only zvol dictionary)'
        )
        return 1

    # Print error if zvol dictionary missing from self.vm['disk']
    if 'zvol' not in vm['disk']:
        error_print(error_prefix, 'missing zvol dictionary in vm[\'disk\']')
        return 1

    # Check if base zvol (to be cloned) specified
    if 'base' not in vm['disk']['zvol']:
        error_print(
            error_prefix, 'base cloud image not specified in zvol dictionary'
        )
        return 1

    # Move zvol options to separate dictionary
    zvol = vm['disk']['zvol']
    del vm['disk']['zvol']

    # Return dictionaries in single dictionary
    return {
        'userdata': userdata,
        'metadata': metadata,
        'vm': vm,
        'zvol': zvol
    }


# zvol_destroy(): attempts to destroy the specified zvol, or prints error
def zvol_destroy(name, error_prefix):
    try:
        zfs_cli.destroy(name)
    except:
        error_print(
            error_prefix, 'zvol was created but could not be destroyed, '
            + 'manual deletion required'
        )
        return 1
    return 0


# VirtualMachine class: main class containing all VM creation functions. Takes
# dictionary containing all qvm dictionaries; see import_yaml()
class VirtualMachine(object):
    def __init__(self, qvm_dict):
        # Import all dictionaries
        self.userdata = qvm_dict['userdata']
        self.metadata = qvm_dict['metadata']
        self.vm = qvm_dict['vm']
        self.zvol = qvm_dict['zvol']

        # Set cloud-init ISO path as CD-ROM to be attached to VM
        self.vm['cdrom'] = '/tmp/qvm{}/seed.iso'.format(str(randrange(999999)))

        # Set base image variable
        self.zvol_base = self.zvol['base'] + '@base'
        del self.zvol['base']

        # zvol to be created (and/or destroyed on error)
        self.zvol_vm = '{}/{}'.format(
            self.zvol_base.rpartition('/')[0],
            self.vm['name']
        )

        # Set VM disk path
        self.vm['disk']['path'] = '/dev/zvol/' + self.zvol_vm

    # create_cloudinit_iso(): Creates seed.iso to be attached to created VM in
    # /tmp/qvm<randint>/
    def create_cloudinit_iso(self):
        error_prefix = 'Error creating cloud-init image: '

        # Get cloud-init directory
        cloudinit_dir = os.path.dirname(self.vm['cdrom']) + '/'

        # Make cloud-init directory
        try:
            os.mkdir(cloudinit_dir)
        except OSError:
            error_print(error_prefix, 'failed to create cloud-init directory')
            return 1

        # Dump cloud-init YAML documents into corresponding files
        with open(cloudinit_dir + 'user-data', 'w') as userdata_file:
            userdata_file.write(yaml.dump(self.userdata))
        with open(cloudinit_dir + 'meta-data', 'w') as metadata_file:
            metadata_file.write(yaml.dump(self.metadata))
        
        # Create image or print error
        iso_creation_cmd = [
            'genisoimage',
            '-output',
            self.vm['cdrom'],
            '-volid',
            'cidata',
            '-joliet',
            '-rock',
            cloudinit_dir + 'user-data',
            cloudinit_dir + 'meta-data'
        ]
        try:
            subprocess.check_output(iso_creation_cmd)
        except subprocess.CalledProcessError:
            error_print(error_prefix, 'create command failed')
            return 1
        
        # Success message
        print('cloud-init image created in ' + cloudinit_dir)
        return 0

    # clone_base_zvol(): Creates a clone of the cloud image base snapshot
    # (<cloudimg>@base) for the new VM.
    def clone_base_zvol(self):
        error_prefix = 'Error cloning zvol {}: '.format(self.zvol_vm)

        # Clone base zvol, or print error and revert
        try:
            zfs_cli.clone(self.zvol_vm, self.zvol_base, props=self.zvol)
        except:
            error_print(error_prefix, 'command failed')
            zvol_destroy(self.zvol_vm, error_prefix)
            return 1

        # Success message
        print('zvol {} created'.format(self.zvol_vm))
        return 0

    # build_cmd(): Builds the full virt-install command for creating the VM
    def build_cmd(self):
        # Build base command
        # --noautoconsole to close virt-install on VM startup
        self.cmd = ['virt-install', '--noautoconsole']

        # Cycle through each option from imported YAML
        for key, value in self.vm.iteritems():
            # For nested options
            if type(value) is DictType:
                cmdtmp = ''
                self.cmd.append('--' + key)
                # Build command into a string, append string to cmd list
                for childkey, childvalue in value.iteritems():
                    cmdtmp = '{}{}={},'.format(
                        cmdtmp, childkey, str(childvalue)
                    )
                self.cmd.append(cmdtmp)
            # For options with no sub-options
            elif type(value) is BooleanType:
                self.cmd.append('--' + key)
            # All other options
            elif type(value) is IntType or StringType:
                self.cmd.extend(['--' + key, str(value)])
        return 0

    # create(): Runs the command built by build_cmd(). First validates to
    # output any errors to STDERR 
    def create(self):
        error_prefix = 'Error creating VM: '

        # Validate VM prior to install
        try:
            subprocess.check_output(
                self.cmd + ['--dry-run'], stderr=subprocess.STDOUT
            )
        except subprocess.CalledProcessError as e:
            error_print(error_prefix, e.output)
            zvol_destroy(self.zvol_vm, error_prefix)
            return 1

        # Create if validation passes
        try:
            subprocess.check_output(self.cmd, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as e:
            error_print(error_prefix, e.output)
            zvol_destroy(self.zvol_vm, error_prefix)
            return 1

        # VM creation completion message
        print('VM {} created'.format(self.vm['name']))
        return 0


# import_cloud_img(): Creates new zvol and writes specified image to it.
# Accepts optional dictionary of properties for zvol creation
def import_cloud_img(name, img_source, props=None):
    error_prefix = 'Error importing cloud image: '

    # Check if image exists
    if os.path.exists(img_source) is False:
        error_print(error_prefix, 'image not found')
        return 1

    # Set reasonable zvol defaults. refreservation='none' for sparse.
    if props is None:
        props = {'volblocksize': '16K', 'refreservation': 'none'}

    # Get cloud image size
    try:
        img_size = os.path.getsize(img_source)
    except OSError:
        error_print(error_prefix, 'could not get source image size')
        return 1

    # Convert image size to MiB
    props['volsize'] = str(int(ceil(float(img_size) / (1024**2)))) + 'M'

    # Open image file, if failed print error
    try:
        img = open(img_source, 'r')
    except IOError:
        error_print(error_prefix, 'could not open image source')
        return 1

    # Create zvol
    print('Creating zvol for cloud image...', end='')
    sys.stdout.flush()  # flush stdout to display above message immediately

    try:
        zfs_cli.create(name, ds_type='zvol', props=props)

    except libzfs_core.exceptions.FilesystemExists:
        print('failed')
        error_print(error_prefix, 'zvol already exists')
        return 1

    except libzfs_core.exceptions.ParentNotFound:
        print('failed')
        error_print(error_prefix, 'parent dataset not found')
        return 1

    except libzfs_core.exceptions.PoolNotFound:
        print('failed')
        error_print(error_prefix, 'pool not found or pool name missing')
        return 1

    except libzfs_core.exceptions.PropertyInvalid:
        print('failed')
        error_print(error_prefix, 'invalid zvol property')
        return 1

    except libzfs_core.exceptions.NameInvalid:
        print('failed')
        error_print(error_prefix, 'invalid zvol name')
        return 1

    except libzfs_core.exceptions.NameTooLong:
        print('failed')
        error_print(error_prefix, 'zvol name is too long')
        return 1

    except libzfs_core.exceptions.ZFSInitializationFailed as e:
        print('failed')
        # Message for permissions errors
        if e.errno == errno.EPERM:
            error_print(
                error_prefix, 'failed to initialise ZFS, could be permissions'
            )
        # All other initialisation errors
        else:
            error_print(error_prefix, 'ZFS failed to initialise')
        return 1

    print('done')

    # Set path for zvol block device
    zvol_dev = '/dev/zvol/' + name

    # Open zvol file, if failed print error and destroy zvol
    if os.path.islink(zvol_dev) is True:
        try:
            zvol = open(zvol_dev, 'w')
        except IOError:
            error_print(error_prefix, 'could not open zvol device')
            zvol_destroy(name, error_prefix)
            return 1
    else:
        error_print(error_prefix, 'zvol block device failed to create')
        zvol_destroy(name, error_prefix)
        return 1

    # Write image to zvol message
    print('Writing cloud image to zvol...', end='')
    sys.stdout.flush()  # flush stdout to display above message immediately

    # Write image to zvol and flush data from buffers to disk
    zvol.write(img.read())
    zvol.flush()
    os.fsync(zvol.fileno())

    # Completion message
    print('done')

    # Create base snapshot, if failed print error and destroy zvol
    print('Creating base snapshot...', end='')
    try:
        libzfs_core.lzc_snapshot([str(name + '@base')])
    except libzfs_core.exceptions.SnapshotFailure:
        print('failed')
        error_print(error_prefix, 'could not create base snapshot')
        zvol_destroy(name, error_prefix)
        return 1

    print('done')
    return 0


def usage_message():
    error_print(
        'qvm usage:\n',
        '\tqvm vm QVMFILE - create new virtual machine from qvm file\n'
        + '\tqvm image CLOUD_IMAGE ZVOL - import new cloud image to '
        + 'specified zvol'
    )


def main():
    if len(sys.argv) < 3:
        usage_message()
        return 1

    # Process arguments - not using argparse, too few options to justify
    if sys.argv[1] == 'vm' and len(sys.argv) == 3:
        yaml_doc = import_yaml(os.path.expanduser(sys.argv[2]))
        if type(yaml_doc) is DictType:
            vm = VirtualMachine(yaml_doc)
        else:
            return 1
        if vm.create_cloudinit_iso() == 1:
            return 1
        if vm.clone_base_zvol() == 1:
            return 1
        if vm.build_cmd() == 1:
            return 1
        if vm.create() == 1:
            return 1
    elif sys.argv[1] == 'image' and len(sys.argv) == 4:
        import_cloud_img(os.path.expanduser(sys.argv[3]), sys.argv[2])
    else:
        usage_message()
        return 1

    return 0


if __name__ == "__main__":
    main()
