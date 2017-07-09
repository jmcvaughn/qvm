# Standard library
from __future__ import print_function
import errno
import subprocess
import sys

# Extra packages
from libzfs_core import exceptions as pyzfs_exceptions

# This module
from . import exceptions


def exception_mapper(output):
    # Get third (last) partition of CLI error string
    output_trail = output.rpartition(':')[2].strip()

    # Search through exception mappings, return if match
    for key,value in exceptions.mappings.iteritems():
        if key in output_trail:
            return value

    # Otherwise return generic error
    return 'ZFSGenericError'


def raise_exception(output, name):
    # If permission denied error, raise appropriate exception
    if output == 'Permission denied the ZFS utilities must be run as root.\n':
        raise pyzfs_exceptions.ZFSInitializationFailed(errno.EPERM)

    mapped_exception = exception_mapper(output)

    if mapped_exception == 'ZFSGenericError':
        raise pyzfs_exceptions.ZFSGenericError(1, name, output)

    # Otherwise, run map exception and raise the error as normal
    raise getattr(pyzfs_exceptions, mapped_exception)(name)


def run_cmd(cmd):
    try:
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        raise_exception(e.output, cmd[-1])


def create(name, ds_type='zfs', props=None):
    # Build base command
    cmd = ['zfs', 'create']

    if ds_type == 'zvol' and props is None:
        print(
            'Error creating zvol: properties dictionary is required',
            file=sys.stderr
        )
        return 1

    # Add each option to the command
    for key,value in props.iteritems():
        if key == 'volsize':
            cmd.extend(['-V', value])
        else:
            cmd.extend(['-o', '{}={}'.format(key, value)])

    # Add dataset name as final argument
    cmd.append(name)

    # Run the command, raise libzfs_core exception returned by the mapper if
    # command fails
    run_cmd(cmd)


def clone(name, origin, props=None):
    # Build base command
    cmd = ['zfs', 'clone']

    # Add each option to the command
    if props is not None or len(props) != 0:
        for key,value in props.iteritems():
            cmd.extend(['-o', '{}={}'.format(key, value)])

    # Add snapshot name (to be cloned) and filesystem/volume
    cmd.extend([origin, name])

    run_cmd(cmd)


def destroy(name):
    run_cmd(['zfs', 'destroy', '-r', name])
