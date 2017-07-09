# qvm
qvm is a Python script for rapidly provisioning virtual machines using
virt-install, cloud-init images and ZFS volumes, with virtual machines being
configured using a single YAML file. It was hastily written as
a proof of concept; it should not be considered usable beyond this by any means.

The code is laid out simply enough; how it works will not be covered here as
a result.

## Pre-requisites
- ZFS
- pyzfs and PyYAML
- virt-install

## Usage
qvm must be run as root user as ZFS on Linux (ZoL) 0.6.x does not feature `zfs
allow/unallow` support. It **should** work as a normal user if using ZoL 0.7.x
and the appropriate permissions have been delegated, however this has not been
tested.
```
sudo qvm vm QVMFILE - create new virtual machine from qvm file
sudo qvm image CLOUD_IMAGE ZVOL - import new cloud image to specified zvol
```

### Image formats
Images imported using qvm must be in raw format. `qemu-img` can be used to
convert images in other formats. For example:
```
$ qemu-img convert -f qcow2 -O raw CentOS-7-x86_64-GenericCloud.qcow2 CentOS-7-x86_64-GenericCloud.raw
```

### qvm file
Virtual machines are defined in a single YAML file containing three documents:
- `vm`: arguments to be passed to virt-install aside from `zvol` (see below)
- `user-data`: cloud-init user-data document
- `meta-data`: cloud-init meta-data document

The `vm` document should only contain key-value pairs, otherwise known as hashes
or dictionaries. Due to the structure of virt-install options, these are easily
mapped to YAML. It must contain a `disk` dictionary containing a `zvol`
sub-dictionary with `base` and `volsize` key-value pairs; this isn't passed to
virt-install; it is used by qvm then removed from the arguments before running.
Refer to [example\_qvm\_file.yaml](example_qvm_file.yaml) as an example.

Each YAML document in a qvm file must contain a key-value pair `qvm: DOCUMENT`,
where `DOCUMENT` is substituted with the corresponding document type as above.
Aside from this, the user-data and meta-data documents in a qvm file are
unchanged: see [cloud-init's
documentation](https://cloudinit.readthedocs.io/en/latest/index.html) for
further guidance on how to use cloud-init using the NoCloud datasource.

### Known issues
qvm doesn't use pyzfs for most operations as it appears that at the time qvm was
created, the libzfs\_core C API did not implement a number of functions for zvol
management. Instead, a pretty horrible CLI-based replica of the required subset
of pyzfs API functions has been created. Errors messages are random or
missing---qvm won't inform you explicitly if a volume by the same name exists
while cloning---and behaviour is unpredictable. As this tool is not intended to
be used beyond its purpose as a proof of concept, it will likely not be fixed or
improved.

cloud-init doesn't appear to run properly most of the time, requiring a manual
run in the virtual machine once up and running ([appears to be the same bug as
reported
here](https://bugs.launchpad.net/ubuntu/+source/cloud-init/+bug/1683974)). As
stated previously, this was only a proof of concept. [See here for guidance on
manually running
cloud-init.](https://stackoverflow.com/questions/23151425/how-to-run-cloud-init-manually)

Dictionaries rather than lists were used for the `vm` YAML document. As
a result, only a single instance of each option is possible; in other words,
only a single disk, network interface, etc., can be used.
