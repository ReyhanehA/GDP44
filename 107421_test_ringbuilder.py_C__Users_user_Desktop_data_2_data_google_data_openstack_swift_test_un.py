# Copyright (c) 2014 Christian Schwede <christian.schwede@enovance.com>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
import mock
import os
import re
import six
import tempfile
import unittest
import uuid
import shlex
import shutil

from swift.cli import ringbuilder
from swift.cli.ringbuilder import EXIT_SUCCESS, EXIT_WARNING, EXIT_ERROR
from swift.common import exceptions
from swift.common.ring import RingBuilder


class RunSwiftRingBuilderMixin(object):

    def run_srb(self, *argv, **kwargs):
        if len(argv) == 1 and isinstance(argv[0], six.string_types):
            # convert a single string to a list
            argv = shlex.split(argv[0])
        mock_stdout = six.StringIO()
        mock_stderr = six.StringIO()

        if 'exp_results' in kwargs:
            exp_results = kwargs['exp_results']
            argv = argv[:-1]
        else:
            exp_results = None

        srb_args = ["", self.tempfile] + [str(s) for s in argv]

        try:
            with mock.patch("sys.stdout", mock_stdout):
                with mock.patch("sys.stderr", mock_stderr):
                    ringbuilder.main(srb_args)
        except SystemExit as err:
            valid_exit_codes = None
            if exp_results is not None and 'valid_exit_codes' in exp_results:
                valid_exit_codes = exp_results['valid_exit_codes']
            else:
                valid_exit_codes = (0, 1)  # (success, warning)

            if err.code not in valid_exit_codes:
                msg = 'Unexpected exit status %s\n' % err.code
                msg += 'STDOUT:\n%s\nSTDERR:\n%s\n' % (
                    mock_stdout.getvalue(), mock_stderr.getvalue())
                self.fail(msg)
        return (mock_stdout.getvalue(), mock_stderr.getvalue())


class TestCommands(unittest.TestCase, RunSwiftRingBuilderMixin):

    def __init__(self, *args, **kwargs):
        super(TestCommands, self).__init__(*args, **kwargs)

        # List of search values for various actions
        # These should all match the first device in the sample ring
        # (see below) but not the second device
        self.search_values = ["d0", "/sda1", "r0", "z0", "z0-127.0.0.1",
                              "127.0.0.1", "z0:6200", ":6200", "R127.0.0.1",
                              "127.0.0.1R127.0.0.1", "R:6200",
                              "_some meta data"]

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        tmpf = tempfile.NamedTemporaryFile(dir=self.tmpdir)
        self.tempfile = self.tmpfile = tmpf.name

    def tearDown(self):
        try:
            shutil.rmtree(self.tmpdir, True)
        except OSError:
            pass

    def create_sample_ring(self, part_power=6):
        """ Create a sample ring with four devices

        At least four devices are needed to test removing
        a device, since having less devices than replicas
        is not allowed.
        """

        # Ensure there is no existing test builder file because
        # create_sample_ring() might be used more than once in a single test
        try:
            os.remove(self.tmpfile)
        except OSError:
            pass

        ring = RingBuilder(part_power, 3, 1)
        ring.add_dev({'weight': 100.0,
                      'region': 0,
                      'zone': 0,
                      'ip': '127.0.0.1',
                      'port': 6200,
                      'device': 'sda1',
                      'meta': 'some meta data',
                      })
        ring.add_dev({'weight': 100.0,
                      'region': 1,
                      'zone': 1,
                      'ip': '127.0.0.2',
                      'port': 6201,
                      'device': 'sda2'
                      })
        ring.add_dev({'weight': 100.0,
                      'region': 2,
                      'zone': 2,
                      'ip': '127.0.0.3',
                      'port': 6202,
                      'device': 'sdc3'
                      })
        ring.add_dev({'weight': 100.0,
                      'region': 3,
                      'zone': 3,
                      'ip': '127.0.0.4',
                      'port': 6203,
                      'device': 'sdd4'
                      })
        ring.save(self.tmpfile)

    def assertSystemExit(self, return_code, func, *argv):
        with self.assertRaises(SystemExit) as cm:
            func(*argv)
        self.assertEqual(return_code, cm.exception.code)

    def test_parse_search_values_old_format(self):
        # Test old format
        argv = ["d0r0z0-127.0.0.1:6200R127.0.0.1:6200/sda1_some meta data"]
        search_values = ringbuilder._parse_search_values(argv)
        self.assertEqual(search_values['id'], 0)
        self.assertEqual(search_values['region'], 0)
        self.assertEqual(search_values['zone'], 0)
        self.assertEqual(search_values['ip'], '127.0.0.1')
        self.assertEqual(search_values['port'], 6200)
        self.assertEqual(search_values['replication_ip'], '127.0.0.1')
        self.assertEqual(search_values['replication_port'], 6200)
        self.assertEqual(search_values['device'], 'sda1')
        self.assertEqual(search_values['meta'], 'some meta data')

    def test_parse_search_values_new_format(self):
        # Test new format
        argv = ["--id", "0", "--region", "0", "--zone", "0",
                "--ip", "127.0.0.1",
                "--port", "6200",
                "--replication-ip", "127.0.0.1",
                "--replication-port", "6200",
                "--device", "sda1", "--meta", "some meta data",
                "--weight", "100"]
        search_values = ringbuilder._parse_search_values(argv)
        self.assertEqual(search_values['id'], 0)
        self.assertEqual(search_values['region'], 0)
        self.assertEqual(search_values['zone'], 0)
        self.assertEqual(search_values['ip'], '127.0.0.1')
        self.assertEqual(search_values['port'], 6200)
        self.assertEqual(search_values['replication_ip'], '127.0.0.1')
        self.assertEqual(search_values['replication_port'], 6200)
        self.assertEqual(search_values['device'], 'sda1')
        self.assertEqual(search_values['meta'], 'some meta data')
        self.assertEqual(search_values['weight'], 100)

    def test_parse_search_values_number_of_arguments(self):
        # Test Number of arguments abnormal
        argv = ["--region", "2", "test"]
        self.assertSystemExit(
            EXIT_ERROR, ringbuilder._parse_search_values, argv)

    def test_find_parts(self):
        rb = RingBuilder(8, 3, 0)
        rb.add_dev({'id': 0, 'region': 1, 'zone': 0, 'weight': 100,
                    'ip': '127.0.0.1', 'port': 10000, 'device': 'sda1'})
        rb.add_dev({'id': 3, 'region': 1, 'zone': 0, 'weight': 100,
                    'ip': '127.0.0.1', 'port': 10000, 'device': 'sdb1'})
        rb.add_dev({'id': 1, 'region': 1, 'zone': 1, 'weight': 100,
                    'ip': '127.0.0.1', 'port': 10001, 'device': 'sda1'})
        rb.add_dev({'id': 4, 'region': 1, 'zone': 1, 'weight': 100,
                    'ip': '127.0.0.1', 'port': 10001, 'device': 'sdb1'})
        rb.add_dev({'id': 2, 'region': 1, 'zone': 2, 'weight': 100,
                    'ip': '127.0.0.1', 'port': 10002, 'device': 'sda1'})
        rb.add_dev({'id': 5, 'region': 1, 'zone': 2, 'weight': 100,
                    'ip': '127.0.0.1', 'port': 10002, 'device': 'sdb1'})
        rb.rebalance()

        rb.add_dev({'id': 6, 'region': 2, 'zone': 1, 'weight': 10,
                    'ip': '127.0.0.1', 'port': 10004, 'device': 'sda1'})
        rb.pretend_min_part_hours_passed()
        rb.rebalance()

        ringbuilder.builder = rb
        sorted_partition_count = ringbuilder._find_parts(
            rb.search_devs({'ip': '127.0.0.1'}))

        # Expect 256 partitions in the output
        self.assertEqual(256, len(sorted_partition_count))

        # Each partitions should have 3 replicas
        for partition, count in sorted_partition_count:
            self.assertEqual(
                3, count, "Partition %d has only %d replicas" %
                (partition, count))

    def test_parse_list_parts_values_number_of_arguments(self):
        # Test Number of arguments abnormal
        argv = ["--region", "2", "test"]
        self.assertSystemExit(
            EXIT_ERROR, ringbuilder._parse_list_parts_values, argv)

    def test_parse_add_values_number_of_arguments(self):
        # Test Number of arguments abnormal
        argv = ["--region", "2", "test"]
        self.assertSystemExit(
            EXIT_ERROR, ringbuilder._parse_add_values, argv)

    def test_set_weight_values_no_devices(self):
        # Test no devices
        # _set_weight_values doesn't take argv-like arguments
        self.assertSystemExit(
            EXIT_ERROR, ringbuilder._set_weight_values, [], 100)

    def test_parse_set_weight_values_number_of_arguments(self):
        # Test Number of arguments abnormal
        argv = ["r1", "100", "r2"]
        self.assertSystemExit(
            EXIT_ERROR, ringbuilder._parse_set_weight_values, argv)

        argv = ["--region", "2"]
        self.assertSystemExit(
            EXIT_ERROR, ringbuilder._parse_set_weight_values, argv)

    def test_set_info_values_no_devices(self):
        # Test no devices
        # _set_info_values doesn't take argv-like arguments
        self.assertSystemExit(
            EXIT_ERROR, ringbuilder._set_info_values, [], 100)

    def test_parse_set_info_values_number_of_arguments(self):
        # Test Number of arguments abnormal
        argv = ["r1", "127.0.0.1", "r2"]
        self.assertSystemExit(
            EXIT_ERROR, ringbuilder._parse_set_info_values, argv)

    def test_parse_remove_values_number_of_arguments(self):
        # Test Number of arguments abnormal
        argv = ["--region", "2", "test"]
        self.assertSystemExit(
            EXIT_ERROR, ringbuilder._parse_remove_values, argv)

    def test_create_ring(self):
        argv = ["", self.tmpfile, "create", "6", "3.14159265359", "1"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)
        ring = RingBuilder.load(self.tmpfile)
        self.assertEqual(ring.part_power, 6)
        self.assertEqual(ring.replicas, 3.14159265359)
        self.assertEqual(ring.min_part_hours, 1)

    def test_create_ring_number_of_arguments(self):
        # Test missing arguments
        argv = ["", self.tmpfile, "create"]
        self.assertSystemExit(EXIT_ERROR, ringbuilder.main, argv)

    def test_add_device_ipv4_old_format(self):
        self.create_sample_ring()
        # Test ipv4(old format)
        argv = ["", self.tmpfile, "add",
                "r2z3-127.0.0.1:6200/sda3_some meta data", "3.14159265359"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)

        # Check that device was created with given data
        ring = RingBuilder.load(self.tmpfile)
        dev = ring.devs[-1]
        self.assertEqual(dev['region'], 2)
        self.assertEqual(dev['zone'], 3)
        self.assertEqual(dev['ip'], '127.0.0.1')
        self.assertEqual(dev['port'], 6200)
        self.assertEqual(dev['device'], 'sda3')
        self.assertEqual(dev['weight'], 3.14159265359)
        self.assertEqual(dev['replication_ip'], '127.0.0.1')
        self.assertEqual(dev['replication_port'], 6200)
        self.assertEqual(dev['meta'], 'some meta data')

    def test_add_duplicate_devices(self):
        self.create_sample_ring()
        # Test adding duplicate devices
        argv = ["", self.tmpfile, "add",
                "r1z1-127.0.0.1:6200/sda9", "3.14159265359",
                "r1z1-127.0.0.1:6200/sda9", "2"]
        self.assertSystemExit(EXIT_ERROR, ringbuilder.main, argv)

    def test_add_device_ipv6_old_format(self):
        self.create_sample_ring()
        # Test ipv6(old format)
        argv = \
            ["", self.tmpfile, "add",
             "r2z3-2001:0000:1234:0000:0000:C1C0:ABCD:0876:6200"
             "R2::10:7000/sda3_some meta data",
             "3.14159265359"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)

        # Check that device was created with given data
        ring = RingBuilder.load(self.tmpfile)
        dev = ring.devs[-1]
        self.assertEqual(dev['region'], 2)
        self.assertEqual(dev['zone'], 3)
        self.assertEqual(dev['ip'], '2001:0:1234::c1c0:abcd:876')
        self.assertEqual(dev['port'], 6200)
        self.assertEqual(dev['device'], 'sda3')
        self.assertEqual(dev['weight'], 3.14159265359)
        self.assertEqual(dev['replication_ip'], '2::10')
        self.assertEqual(dev['replication_port'], 7000)
        self.assertEqual(dev['meta'], 'some meta data')
        # Final check, rebalance and check ring is ok
        ring.rebalance()
        self.assertTrue(ring.validate())

    def test_add_device_ipv4_new_format(self):
        self.create_sample_ring()
        # Test ipv4(new format)
        argv = \
            ["", self.tmpfile, "add",
             "--region", "2", "--zone", "3",
             "--ip", "127.0.0.2",
             "--port", "6200",
             "--replication-ip", "127.0.0.2",
             "--replication-port", "6200",
             "--device", "sda3", "--meta", "some meta data",
             "--weight", "3.14159265359"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)

        # Check that device was created with given data
        ring = RingBuilder.load(self.tmpfile)
        dev = ring.devs[-1]
        self.assertEqual(dev['region'], 2)
        self.assertEqual(dev['zone'], 3)
        self.assertEqual(dev['ip'], '127.0.0.2')
        self.assertEqual(dev['port'], 6200)
        self.assertEqual(dev['device'], 'sda3')
        self.assertEqual(dev['weight'], 3.14159265359)
        self.assertEqual(dev['replication_ip'], '127.0.0.2')
        self.assertEqual(dev['replication_port'], 6200)
        self.assertEqual(dev['meta'], 'some meta data')
        # Final check, rebalance and check ring is ok
        ring.rebalance()
        self.assertTrue(ring.validate())

    def test_add_device_ipv6_new_format(self):
        self.create_sample_ring()
        # Test ipv6(new format)
        argv = \
            ["", self.tmpfile, "add",
             "--region", "2", "--zone", "3",
             "--ip", "[3001:0000:1234:0000:0000:C1C0:ABCD:0876]",
             "--port", "6200",
             "--replication-ip", "[3::10]",
             "--replication-port", "7000",
             "--device", "sda3", "--meta", "some meta data",
             "--weight", "3.14159265359"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)

        # Check that device was created with given data
        ring = RingBuilder.load(self.tmpfile)
        dev = ring.devs[-1]
        self.assertEqual(dev['region'], 2)
        self.assertEqual(dev['zone'], 3)
        self.assertEqual(dev['ip'], '3001:0:1234::c1c0:abcd:876')
        self.assertEqual(dev['port'], 6200)
        self.assertEqual(dev['device'], 'sda3')
        self.assertEqual(dev['weight'], 3.14159265359)
        self.assertEqual(dev['replication_ip'], '3::10')
        self.assertEqual(dev['replication_port'], 7000)
        self.assertEqual(dev['meta'], 'some meta data')
        # Final check, rebalance and check ring is ok
        ring.rebalance()
        self.assertTrue(ring.validate())

    def test_add_device_domain_new_format(self):
        self.create_sample_ring()
        # Test domain name
        argv = \
            ["", self.tmpfile, "add",
             "--region", "2", "--zone", "3",
             "--ip", "test.test.com",
             "--port", "6200",
             "--replication-ip", "r.test.com",
             "--replication-port", "7000",
             "--device", "sda3", "--meta", "some meta data",
             "--weight", "3.14159265359"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)

        # Check that device was created with given data
        ring = RingBuilder.load(self.tmpfile)
        dev = ring.devs[-1]
        self.assertEqual(dev['region'], 2)
        self.assertEqual(dev['zone'], 3)
        self.assertEqual(dev['ip'], 'test.test.com')
        self.assertEqual(dev['port'], 6200)
        self.assertEqual(dev['device'], 'sda3')
        self.assertEqual(dev['weight'], 3.14159265359)
        self.assertEqual(dev['replication_ip'], 'r.test.com')
        self.assertEqual(dev['replication_port'], 7000)
        self.assertEqual(dev['meta'], 'some meta data')
        # Final check, rebalance and check ring is ok
        ring.rebalance()
        self.assertTrue(ring.validate())

    def test_add_device_number_of_arguments(self):
        # Test Number of arguments abnormal
        argv = ["", self.tmpfile, "add"]
        self.assertSystemExit(EXIT_ERROR, ringbuilder.main, argv)

    def test_add_device_already_exists(self):
        # Test Add a device that already exists
        argv = ["", self.tmpfile, "add",
                "r0z0-127.0.0.1:6200/sda1_some meta data", "100"]
        self.assertSystemExit(EXIT_ERROR, ringbuilder.main, argv)

    def test_add_device_old_missing_region(self):
        self.create_sample_ring()
        # Test add device without specifying a region
        argv = ["", self.tmpfile, "add",
                "z3-127.0.0.1:6200/sde3_some meta data", "3.14159265359"]
        exp_results = {'valid_exit_codes': [2]}
        self.run_srb(*argv, exp_results=exp_results)
        # Check that ring was created with sane value for region
        ring = RingBuilder.load(self.tmpfile)
        dev = ring.devs[-1]
        self.assertTrue(dev['region'] > 0)

    def test_remove_device(self):
        for search_value in self.search_values:
            self.create_sample_ring()
            argv = ["", self.tmpfile, "remove", search_value]
            self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)
            ring = RingBuilder.load(self.tmpfile)

            # Check that weight was set to 0
            dev = ring.devs[0]
            self.assertEqual(dev['weight'], 0)

            # Check that device is in list of devices to be removed
            self.assertEqual(dev['region'], 0)
            self.assertEqual(dev['zone'], 0)
            self.assertEqual(dev['ip'], '127.0.0.1')
            self.assertEqual(dev['port'], 6200)
            self.assertEqual(dev['device'], 'sda1')
            self.assertEqual(dev['weight'], 0)
            self.assertEqual(dev['replication_ip'], '127.0.0.1')
            self.assertEqual(dev['replication_port'], 6200)
            self.assertEqual(dev['meta'], 'some meta data')

            # Check that second device in ring is not affected
            dev = ring.devs[1]
            self.assertEqual(dev['weight'], 100)
            self.assertFalse([d for d in ring._remove_devs if d['id'] == 1])

            # Final check, rebalance and check ring is ok
            ring.rebalance()
            self.assertTrue(ring.validate())

    def test_remove_device_ipv4_old_format(self):
        self.create_sample_ring()
        # Test ipv4(old format)
        argv = ["", self.tmpfile, "remove",
                "d0r0z0-127.0.0.1:6200R127.0.0.1:6200/sda1_some meta data"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)
        ring = RingBuilder.load(self.tmpfile)

        # Check that weight was set to 0
        dev = ring.devs[0]
        self.assertEqual(dev['weight'], 0)

        # Check that device is in list of devices to be removed
        self.assertEqual(dev['region'], 0)
        self.assertEqual(dev['zone'], 0)
        self.assertEqual(dev['ip'], '127.0.0.1')
        self.assertEqual(dev['port'], 6200)
        self.assertEqual(dev['device'], 'sda1')
        self.assertEqual(dev['weight'], 0)
        self.assertEqual(dev['replication_ip'], '127.0.0.1')
        self.assertEqual(dev['replication_port'], 6200)
        self.assertEqual(dev['meta'], 'some meta data')

        # Check that second device in ring is not affected
        dev = ring.devs[1]
        self.assertEqual(dev['weight'], 100)
        self.assertFalse([d for d in ring._remove_devs if d['id'] == 1])

        # Final check, rebalance and check ring is ok
        ring.rebalance()
        self.assertTrue(ring.validate())

    def test_remove_device_ipv6_old_format(self):
        self.create_sample_ring()
        # add IPV6
        argv = \
            ["", self.tmpfile, "add",
             "--region", "2", "--zone", "3",
             "--ip", "[2001:0000:1234:0000:0000:C1C0:ABCD:0876]",
             "--port", "6200",
             "--replication-ip", "[2::10]",
             "--replication-port", "7000",
             "--device", "sda3", "--meta", "some meta data",
             "--weight", "3.14159265359"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)

        # Test ipv6(old format)
        argv = ["", self.tmpfile, "remove",
                "d4r2z3-[2001:0000:1234:0000:0000:C1C0:ABCD:0876]:6200"
                "R[2::10]:7000/sda3_some meta data"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)
        ring = RingBuilder.load(self.tmpfile)

        # Check that second device in ring is not affected
        dev = ring.devs[0]
        self.assertEqual(dev['weight'], 100)
        self.assertFalse([d for d in ring._remove_devs if d['id'] == 0])

        # Check that second device in ring is not affected
        dev = ring.devs[1]
        self.assertEqual(dev['weight'], 100)
        self.assertFalse([d for d in ring._remove_devs if d['id'] == 1])

        # Check that weight was set to 0
        dev = ring.devs[-1]
        self.assertEqual(dev['weight'], 0)

        # Check that device is in list of devices to be removed
        self.assertEqual(dev['region'], 2)
        self.assertEqual(dev['zone'], 3)
        self.assertEqual(dev['ip'], '2001:0:1234::c1c0:abcd:876')
        self.assertEqual(dev['port'], 6200)
        self.assertEqual(dev['device'], 'sda3')
        self.assertEqual(dev['weight'], 0)
        self.assertEqual(dev['replication_ip'], '2::10')
        self.assertEqual(dev['replication_port'], 7000)
        self.assertEqual(dev['meta'], 'some meta data')

        # Final check, rebalance and check ring is ok
        ring.rebalance()
        self.assertTrue(ring.validate())

    def test_remove_device_ipv4_new_format(self):
        self.create_sample_ring()
        # Test ipv4(new format)
        argv = \
            ["", self.tmpfile, "remove",
             "--id", "0", "--region", "0", "--zone", "0",
             "--ip", "127.0.0.1",
             "--port", "6200",
             "--replication-ip", "127.0.0.1",
             "--replication-port", "6200",
             "--device", "sda1", "--meta", "some meta data"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)
        ring = RingBuilder.load(self.tmpfile)

        # Check that weight was set to 0
        dev = ring.devs[0]
        self.assertEqual(dev['weight'], 0)

        # Check that device is in list of devices to be removed
        self.assertEqual(dev['region'], 0)
        self.assertEqual(dev['zone'], 0)
        self.assertEqual(dev['ip'], '127.0.0.1')
        self.assertEqual(dev['port'], 6200)
        self.assertEqual(dev['device'], 'sda1')
        self.assertEqual(dev['weight'], 0)
        self.assertEqual(dev['replication_ip'], '127.0.0.1')
        self.assertEqual(dev['replication_port'], 6200)
        self.assertEqual(dev['meta'], 'some meta data')

        # Check that second device in ring is not affected
        dev = ring.devs[1]
        self.assertEqual(dev['weight'], 100)
        self.assertFalse([d for d in ring._remove_devs if d['id'] == 1])

        # Final check, rebalance and check ring is ok
        ring.rebalance()
        self.assertTrue(ring.validate())

    def test_remove_device_ipv6_new_format(self):
        self.create_sample_ring()
        argv = \
            ["", self.tmpfile, "add",
             "--region", "2", "--zone", "3",
             "--ip", "[3001:0000:1234:0000:0000:C1C0:ABCD:0876]",
             "--port", "8000",
             "--replication-ip", "[3::10]",
             "--replication-port", "9000",
             "--device", "sda30", "--meta", "other meta data",
             "--weight", "3.14159265359"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)

        # Test ipv6(new format)
        argv = \
            ["", self.tmpfile, "remove",
             "--id", "4", "--region", "2", "--zone", "3",
             "--ip", "[3001:0000:1234:0000:0000:C1C0:ABCD:0876]",
             "--port", "8000",
             "--replication-ip", "[3::10]",
             "--replication-port", "9000",
             "--device", "sda30", "--meta", "other meta data"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)
        ring = RingBuilder.load(self.tmpfile)

        # Check that second device in ring is not affected
        dev = ring.devs[0]
        self.assertEqual(dev['weight'], 100)
        self.assertFalse([d for d in ring._remove_devs if d['id'] == 0])

        # Check that second device in ring is not affected
        dev = ring.devs[1]
        self.assertEqual(dev['weight'], 100)
        self.assertFalse([d for d in ring._remove_devs if d['id'] == 1])

        # Check that weight was set to 0
        dev = ring.devs[-1]
        self.assertEqual(dev['weight'], 0)

        # Check that device is in list of devices to be removed
        self.assertEqual(dev['region'], 2)
        self.assertEqual(dev['zone'], 3)
        self.assertEqual(dev['ip'], '3001:0:1234::c1c0:abcd:876')
        self.assertEqual(dev['port'], 8000)
        self.assertEqual(dev['device'], 'sda30')
        self.assertEqual(dev['weight'], 0)
        self.assertEqual(dev['replication_ip'], '3::10')
        self.assertEqual(dev['replication_port'], 9000)
        self.assertEqual(dev['meta'], 'other meta data')

        # Final check, rebalance and check ring is ok
        ring.rebalance()
        self.assertTrue(ring.validate())

    def test_remove_device_domain_new_format(self):
        self.create_sample_ring()
        # add domain name
        argv = \
            ["", self.tmpfile, "add",
             "--region", "2", "--zone", "3",
             "--ip", "test.test.com",
             "--port", "6200",
             "--replication-ip", "r.test.com",
             "--replication-port", "7000",
             "--device", "sda3", "--meta", "some meta data",
             "--weight", "3.14159265359"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)

        # Test domain name
        argv = \
            ["", self.tmpfile, "remove",
             "--id", "4", "--region", "2", "--zone", "3",
             "--ip", "test.test.com",
             "--port", "6200",
             "--replication-ip", "r.test.com",
             "--replication-port", "7000",
             "--device", "sda3", "--meta", "some meta data"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)
        ring = RingBuilder.load(self.tmpfile)

        # Check that second device in ring is not affected
        dev = ring.devs[0]
        self.assertEqual(dev['weight'], 100)
        self.assertFalse([d for d in ring._remove_devs if d['id'] == 0])

        # Check that second device in ring is not affected
        dev = ring.devs[1]
        self.assertEqual(dev['weight'], 100)
        self.assertFalse([d for d in ring._remove_devs if d['id'] == 1])

        # Check that weight was set to 0
        dev = ring.devs[-1]
        self.assertEqual(dev['weight'], 0)

        # Check that device is in list of devices to be removed
        self.assertEqual(dev['region'], 2)
        self.assertEqual(dev['zone'], 3)
        self.assertEqual(dev['ip'], 'test.test.com')
        self.assertEqual(dev['port'], 6200)
        self.assertEqual(dev['device'], 'sda3')
        self.assertEqual(dev['weight'], 0)
        self.assertEqual(dev['replication_ip'], 'r.test.com')
        self.assertEqual(dev['replication_port'], 7000)
        self.assertEqual(dev['meta'], 'some meta data')

        # Final check, rebalance and check ring is ok
        ring.rebalance()
        self.assertTrue(ring.validate())

    def test_remove_device_number_of_arguments(self):
        self.create_sample_ring()
        # Test Number of arguments abnormal
        argv = ["", self.tmpfile, "remove"]
        self.assertSystemExit(EXIT_ERROR, ringbuilder.main, argv)

    def test_remove_device_no_matching(self):
        self.create_sample_ring()
        # Test No matching devices
        argv = ["", self.tmpfile, "remove",
                "--ip", "unknown"]
        self.assertSystemExit(EXIT_ERROR, ringbuilder.main, argv)

    def test_set_weight(self):
        for search_value in self.search_values:
            self.create_sample_ring()

            argv = ["", self.tmpfile, "set_weight",
                    search_value, "3.14159265359"]
            self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)
            ring = RingBuilder.load(self.tmpfile)

            # Check that weight was changed
            dev = ring.devs[0]
            self.assertEqual(dev['weight'], 3.14159265359)

            # Check that second device in ring is not affected
            dev = ring.devs[1]
            self.assertEqual(dev['weight'], 100)

            # Final check, rebalance and check ring is ok
            ring.rebalance()
            self.assertTrue(ring.validate())

    def test_set_weight_ipv4_old_format(self):
        self.create_sample_ring()
        # Test ipv4(old format)
        argv = ["", self.tmpfile, "set_weight",
                "d0r0z0-127.0.0.1:6200R127.0.0.1:6200/sda1_some meta data",
                "3.14159265359"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)
        ring = RingBuilder.load(self.tmpfile)

        # Check that weight was changed
        dev = ring.devs[0]
        self.assertEqual(dev['weight'], 3.14159265359)

        # Check that second device in ring is not affected
        dev = ring.devs[1]
        self.assertEqual(dev['weight'], 100)

        # Final check, rebalance and check ring is ok
        ring.rebalance()
        self.assertTrue(ring.validate())

    def test_set_weight_ipv6_old_format(self):
        self.create_sample_ring()
        # add IPV6
        argv = \
            ["", self.tmpfile, "add",
             "--region", "2", "--zone", "3",
             "--ip", "[2001:0000:1234:0000:0000:C1C0:ABCD:0876]",
             "--port", "6200",
             "--replication-ip", "[2::10]",
             "--replication-port", "7000",
             "--device", "sda3", "--meta", "some meta data",
             "--weight", "100"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)

        # Test ipv6(old format)
        argv = ["", self.tmpfile, "set_weight",
                "d4r2z3-[2001:0000:1234:0000:0000:C1C0:ABCD:0876]:6200"
                "R[2::10]:7000/sda3_some meta data", "3.14159265359"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)
        ring = RingBuilder.load(self.tmpfile)

        # Check that second device in ring is not affected
        dev = ring.devs[0]
        self.assertEqual(dev['weight'], 100)

        # Check that second device in ring is not affected
        dev = ring.devs[1]
        self.assertEqual(dev['weight'], 100)

        # Check that weight was changed
        dev = ring.devs[-1]
        self.assertEqual(dev['weight'], 3.14159265359)

        # Final check, rebalance and check ring is ok
        ring.rebalance()
        self.assertTrue(ring.validate())

    def test_set_weight_ipv4_new_format(self):
        self.create_sample_ring()
        # Test ipv4(new format)
        argv = \
            ["", self.tmpfile, "set_weight",
             "--id", "0", "--region", "0", "--zone", "0",
             "--ip", "127.0.0.1",
             "--port", "6200",
             "--replication-ip", "127.0.0.1",
             "--replication-port", "6200",
             "--device", "sda1", "--meta", "some meta data", "3.14159265359"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)
        ring = RingBuilder.load(self.tmpfile)

        # Check that weight was changed
        dev = ring.devs[0]
        self.assertEqual(dev['weight'], 3.14159265359)

        # Check that second device in ring is not affected
        dev = ring.devs[1]
        self.assertEqual(dev['weight'], 100)

        # Final check, rebalance and check ring is ok
        ring.rebalance()
        self.assertTrue(ring.validate())

    def test_set_weight_ipv6_new_format(self):
        self.create_sample_ring()
        # add IPV6
        argv = \
            ["", self.tmpfile, "add",
             "--region", "2", "--zone", "3",
             "--ip", "[2001:0000:1234:0000:0000:C1C0:ABCD:0876]",
             "--port", "6200",
             "--replication-ip", "[2::10]",
             "--replication-port", "7000",
             "--device", "sda3", "--meta", "some meta data",
             "--weight", "100"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)

        # Test ipv6(new format)
        argv = \
            ["", self.tmpfile, "set_weight",
             "--id", "4", "--region", "2", "--zone", "3",
             "--ip", "[2001:0000:1234:0000:0000:C1C0:ABCD:0876]",
             "--port", "6200",
             "--replication-ip", "[2::10]",
             "--replication-port", "7000",
             "--device", "sda3", "--meta", "some meta data", "3.14159265359"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)
        ring = RingBuilder.load(self.tmpfile)

        # Check that second device in ring is not affected
        dev = ring.devs[0]
        self.assertEqual(dev['weight'], 100)

        # Check that second device in ring is not affected
        dev = ring.devs[1]
        self.assertEqual(dev['weight'], 100)

        # Check that weight was changed
        dev = ring.devs[-1]
        self.assertEqual(dev['weight'], 3.14159265359)

        # Final check, rebalance and check ring is ok
        ring.rebalance()
        self.assertTrue(ring.validate())

    def test_set_weight_domain_new_format(self):
        self.create_sample_ring()
        # add domain name
        argv = \
            ["", self.tmpfile, "add",
             "--region", "2", "--zone", "3",
             "--ip", "test.test.com",
             "--port", "6200",
             "--replication-ip", "r.test.com",
             "--replication-port", "7000",
             "--device", "sda3", "--meta", "some meta data",
             "--weight", "100"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)

        # Test domain name
        argv = \
            ["", self.tmpfile, "set_weight",
             "--id", "4", "--region", "2", "--zone", "3",
             "--ip", "test.test.com",
             "--port", "6200",
             "--replication-ip", "r.test.com",
             "--replication-port", "7000",
             "--device", "sda3", "--meta", "some meta data", "3.14159265359"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)
        ring = RingBuilder.load(self.tmpfile)

        # Check that second device in ring is not affected
        dev = ring.devs[0]
        self.assertEqual(dev['weight'], 100)

        # Check that second device in ring is not affected
        dev = ring.devs[1]
        self.assertEqual(dev['weight'], 100)

        # Check that weight was changed
        dev = ring.devs[-1]
        self.assertEqual(dev['weight'], 3.14159265359)

        # Final check, rebalance and check ring is ok
        ring.rebalance()
        self.assertTrue(ring.validate())

    def test_set_weight_number_of_arguments(self):
        self.create_sample_ring()
        # Test Number of arguments abnormal
        argv = ["", self.tmpfile, "set_weight"]
        self.assertSystemExit(EXIT_ERROR, ringbuilder.main, argv)

    def test_set_weight_no_matching(self):
        self.create_sample_ring()
        # Test No matching devices
        argv = ["", self.tmpfile, "set_weight",
                "--ip", "unknown"]
        self.assertSystemExit(EXIT_ERROR, ringbuilder.main, argv)

    def test_set_info(self):
        for search_value in self.search_values:

            self.create_sample_ring()
            argv = ["", self.tmpfile, "set_info", search_value,
                    "127.0.1.1:8000/sda1_other meta data"]
            self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)

            # Check that device was created with given data
            ring = RingBuilder.load(self.tmpfile)
            dev = ring.devs[0]
            self.assertEqual(dev['ip'], '127.0.1.1')
            self.assertEqual(dev['port'], 8000)
            self.assertEqual(dev['device'], 'sda1')
            self.assertEqual(dev['meta'], 'other meta data')

            # Check that second device in ring is not affected
            dev = ring.devs[1]
            self.assertEqual(dev['ip'], '127.0.0.2')
            self.assertEqual(dev['port'], 6201)
            self.assertEqual(dev['device'], 'sda2')
            self.assertEqual(dev['meta'], '')

            # Final check, rebalance and check ring is ok
            ring.rebalance()
            self.assertTrue(ring.validate())

    def test_set_info_ipv4_old_format(self):
        self.create_sample_ring()
        # Test ipv4(old format)
        argv = ["", self.tmpfile, "set_info",
                "d0r0z0-127.0.0.1:6200R127.0.0.1:6200/sda1_some meta data",
                "127.0.1.1:8000R127.0.1.1:8000/sda10_other meta data"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)

        # Check that device was created with given data
        ring = RingBuilder.load(self.tmpfile)
        dev = ring.devs[0]
        self.assertEqual(dev['ip'], '127.0.1.1')
        self.assertEqual(dev['port'], 8000)
        self.assertEqual(dev['replication_ip'], '127.0.1.1')
        self.assertEqual(dev['replication_port'], 8000)
        self.assertEqual(dev['device'], 'sda10')
        self.assertEqual(dev['meta'], 'other meta data')

        # Check that second device in ring is not affected
        dev = ring.devs[1]
        self.assertEqual(dev['ip'], '127.0.0.2')
        self.assertEqual(dev['port'], 6201)
        self.assertEqual(dev['device'], 'sda2')
        self.assertEqual(dev['meta'], '')

        # Final check, rebalance and check ring is ok
        ring.rebalance()
        self.assertTrue(ring.validate())

    def test_set_info_ipv6_old_format(self):
        self.create_sample_ring()
        # add IPV6
        argv = \
            ["", self.tmpfile, "add",
             "--region", "2", "--zone", "3",
             "--ip", "[2001:0000:1234:0000:0000:C1C0:ABCD:0876]",
             "--port", "6200",
             "--replication-ip", "[2::10]",
             "--replication-port", "7000",
             "--device", "sda3", "--meta", "some meta data",
             "--weight", "3.14159265359"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)

        # Test ipv6(old format)
        argv = ["", self.tmpfile, "set_info",
                "d4r2z3-[2001:0000:1234:0000:0000:C1C0:ABCD:0876]:6200"
                "R[2::10]:7000/sda3_some meta data",
                "[3001:0000:1234:0000:0000:C1C0:ABCD:0876]:8000"
                "R[3::10]:8000/sda30_other meta data"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)
        ring = RingBuilder.load(self.tmpfile)

        # Check that second device in ring is not affected
        dev = ring.devs[0]
        self.assertEqual(dev['ip'], '127.0.0.1')
        self.assertEqual(dev['port'], 6200)
        self.assertEqual(dev['replication_ip'], '127.0.0.1')
        self.assertEqual(dev['replication_port'], 6200)
        self.assertEqual(dev['device'], 'sda1')
        self.assertEqual(dev['meta'], 'some meta data')

        # Check that second device in ring is not affected
        dev = ring.devs[1]
        self.assertEqual(dev['ip'], '127.0.0.2')
        self.assertEqual(dev['port'], 6201)
        self.assertEqual(dev['device'], 'sda2')
        self.assertEqual(dev['meta'], '')

        # Check that device was created with given data
        dev = ring.devs[-1]
        self.assertEqual(dev['ip'], '3001:0:1234::c1c0:abcd:876')
        self.assertEqual(dev['port'], 8000)
        self.assertEqual(dev['replication_ip'], '3::10')
        self.assertEqual(dev['replication_port'], 8000)
        self.assertEqual(dev['device'], 'sda30')
        self.assertEqual(dev['meta'], 'other meta data')

        # Final check, rebalance and check ring is ok
        ring.rebalance()
        self.assertTrue(ring.validate())

    def test_set_info_ipv4_new_format(self):
        self.create_sample_ring()
        # Test ipv4(new format)
        argv = \
            ["", self.tmpfile, "set_info",
             "--id", "0", "--region", "0", "--zone", "0",
             "--ip", "127.0.0.1",
             "--port", "6200",
             "--replication-ip", "127.0.0.1",
             "--replication-port", "6200",
             "--device", "sda1", "--meta", "some meta data",
             "--change-ip", "127.0.2.1",
             "--change-port", "9000",
             "--change-replication-ip", "127.0.2.1",
             "--change-replication-port", "9000",
             "--change-device", "sda100", "--change-meta", "other meta data"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)

        # Check that device was created with given data
        ring = RingBuilder.load(self.tmpfile)
        dev = ring.devs[0]
        self.assertEqual(dev['ip'], '127.0.2.1')
        self.assertEqual(dev['port'], 9000)
        self.assertEqual(dev['replication_ip'], '127.0.2.1')
        self.assertEqual(dev['replication_port'], 9000)
        self.assertEqual(dev['device'], 'sda100')
        self.assertEqual(dev['meta'], 'other meta data')

        # Check that second device in ring is not affected
        dev = ring.devs[1]
        self.assertEqual(dev['ip'], '127.0.0.2')
        self.assertEqual(dev['port'], 6201)
        self.assertEqual(dev['device'], 'sda2')
        self.assertEqual(dev['meta'], '')

        # Final check, rebalance and check ring is ok
        ring.rebalance()
        self.assertTrue(ring.validate())

    def test_set_info_ipv6_new_format(self):
        self.create_sample_ring()
        # add IPV6
        argv = \
            ["", self.tmpfile, "add",
             "--region", "2", "--zone", "3",
             "--ip", "[2001:0000:1234:0000:0000:C1C0:ABCD:0876]",
             "--port", "6200",
             "--replication-ip", "[2::10]",
             "--replication-port", "7000",
             "--device", "sda3", "--meta", "some meta data",
             "--weight", "3.14159265359"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)

        # Test ipv6(new format)
        argv = \
            ["", self.tmpfile, "set_info",
             "--id", "4", "--region", "2", "--zone", "3",
             "--ip", "[2001:0000:1234:0000:0000:C1C0:ABCD:0876]",
             "--port", "6200",
             "--replication-ip", "[2::10]",
             "--replication-port", "7000",
             "--device", "sda3", "--meta", "some meta data",
             "--change-ip", "[4001:0000:1234:0000:0000:C1C0:ABCD:0876]",
             "--change-port", "9000",
             "--change-replication-ip", "[4::10]",
             "--change-replication-port", "9000",
             "--change-device", "sda300", "--change-meta", "other meta data"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)
        ring = RingBuilder.load(self.tmpfile)

        # Check that second device in ring is not affected
        dev = ring.devs[0]
        self.assertEqual(dev['ip'], '127.0.0.1')
        self.assertEqual(dev['port'], 6200)
        self.assertEqual(dev['replication_ip'], '127.0.0.1')
        self.assertEqual(dev['replication_port'], 6200)
        self.assertEqual(dev['device'], 'sda1')
        self.assertEqual(dev['meta'], 'some meta data')

        # Check that second device in ring is not affected
        dev = ring.devs[1]
        self.assertEqual(dev['ip'], '127.0.0.2')
        self.assertEqual(dev['port'], 6201)
        self.assertEqual(dev['device'], 'sda2')
        self.assertEqual(dev['meta'], '')

        # Check that device was created with given data
        ring = RingBuilder.load(self.tmpfile)
        dev = ring.devs[-1]
        self.assertEqual(dev['ip'], '4001:0:1234::c1c0:abcd:876')
        self.assertEqual(dev['port'], 9000)
        self.assertEqual(dev['replication_ip'], '4::10')
        self.assertEqual(dev['replication_port'], 9000)
        self.assertEqual(dev['device'], 'sda300')
        self.assertEqual(dev['meta'], 'other meta data')

        # Final check, rebalance and check ring is ok
        ring.rebalance()
        self.assertTrue(ring.validate())

    def test_set_info_domain_new_format(self):
        self.create_sample_ring()
        # add domain name
        argv = \
            ["", self.tmpfile, "add",
             "--region", "2", "--zone", "3",
             "--ip", "test.test.com",
             "--port", "6200",
             "--replication-ip", "r.test.com",
             "--replication-port", "7000",
             "--device", "sda3", "--meta", "some meta data",
             "--weight", "3.14159265359"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)

        # Test domain name
        argv = \
            ["", self.tmpfile, "set_info",
             "--id", "4", "--region", "2", "--zone", "3",
             "--ip", "test.test.com",
             "--port", "6200",
             "--replication-ip", "r.test.com",
             "--replication-port", "7000",
             "--device", "sda3", "--meta", "some meta data",
             "--change-ip", "test.test2.com",
             "--change-port", "9000",
             "--change-replication-ip", "r.test2.com",
             "--change-replication-port", "9000",
             "--change-device", "sda300", "--change-meta", "other meta data"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)
        ring = RingBuilder.load(self.tmpfile)

        # Check that second device in ring is not affected
        dev = ring.devs[0]
        self.assertEqual(dev['ip'], '127.0.0.1')
        self.assertEqual(dev['port'], 6200)
        self.assertEqual(dev['replication_ip'], '127.0.0.1')
        self.assertEqual(dev['replication_port'], 6200)
        self.assertEqual(dev['device'], 'sda1')
        self.assertEqual(dev['meta'], 'some meta data')

        # Check that second device in ring is not affected
        dev = ring.devs[1]
        self.assertEqual(dev['ip'], '127.0.0.2')
        self.assertEqual(dev['port'], 6201)
        self.assertEqual(dev['device'], 'sda2')
        self.assertEqual(dev['meta'], '')

        # Check that device was created with given data
        dev = ring.devs[-1]
        self.assertEqual(dev['ip'], 'test.test2.com')
        self.assertEqual(dev['port'], 9000)
        self.assertEqual(dev['replication_ip'], 'r.test2.com')
        self.assertEqual(dev['replication_port'], 9000)
        self.assertEqual(dev['device'], 'sda300')
        self.assertEqual(dev['meta'], 'other meta data')

        # Final check, rebalance and check ring is ok
        ring.rebalance()
        self.assertTrue(ring.validate())

    def test_set_info_number_of_arguments(self):
        self.create_sample_ring()
        # Test Number of arguments abnormal
        argv = ["", self.tmpfile, "set_info"]
        self.assertSystemExit(EXIT_ERROR, ringbuilder.main, argv)

    def test_set_info_no_matching(self):
        self.create_sample_ring()
        # Test No matching devices
        argv = ["", self.tmpfile, "set_info",
                "--ip", "unknown"]
        self.assertSystemExit(EXIT_ERROR, ringbuilder.main, argv)

    def test_set_info_already_exists(self):
        self.create_sample_ring()
        # Test Set a device that already exists
        argv = \
            ["", self.tmpfile, "set_info",
             "--id", "0", "--region", "0", "--zone", "0",
             "--ip", "127.0.0.1",
             "--port", "6200",
             "--replication-ip", "127.0.0.1",
             "--replication-port", "6200",
             "--device", "sda1", "--meta", "some meta data",
             "--change-ip", "127.0.0.2",
             "--change-port", "6201",
             "--change-replication-ip", "127.0.0.2",
             "--change-replication-port", "6201",
             "--change-device", "sda2", "--change-meta", ""]
        self.assertSystemExit(EXIT_ERROR, ringbuilder.main, argv)

    def test_set_min_part_hours(self):
        self.create_sample_ring()
        argv = ["", self.tmpfile, "set_min_part_hours", "24"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)
        ring = RingBuilder.load(self.tmpfile)
        self.assertEqual(ring.min_part_hours, 24)

    def test_set_min_part_hours_number_of_arguments(self):
        self.create_sample_ring()
        # Test Number of arguments abnormal
        argv = ["", self.tmpfile, "set_min_part_hours"]
        self.assertSystemExit(EXIT_ERROR, ringbuilder.main, argv)

    def test_set_replicas(self):
        self.create_sample_ring()
        argv = ["", self.tmpfile, "set_replicas", "3.14159265359"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)
        ring = RingBuilder.load(self.tmpfile)
        self.assertEqual(ring.replicas, 3.14159265359)

    def test_set_overload(self):
        self.create_sample_ring()
        argv = ["", self.tmpfile, "set_overload", "0.19878"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)
        ring = RingBuilder.load(self.tmpfile)
        self.assertEqual(ring.overload, 0.19878)

    def test_set_overload_negative(self):
        self.create_sample_ring()
        argv = ["", self.tmpfile, "set_overload", "-0.19878"]
        self.assertSystemExit(EXIT_ERROR, ringbuilder.main, argv)
        ring = RingBuilder.load(self.tmpfile)
        self.assertEqual(ring.overload, 0.0)

    def test_set_overload_non_numeric(self):
        self.create_sample_ring()
        argv = ["", self.tmpfile, "set_overload", "swedish fish"]
        self.assertSystemExit(EXIT_ERROR, ringbuilder.main, argv)
        ring = RingBuilder.load(self.tmpfile)
        self.assertEqual(ring.overload, 0.0)

    def test_set_overload_percent(self):
        self.create_sample_ring()
        argv = "set_overload 10%".split()
        out, err = self.run_srb(*argv)
        ring = RingBuilder.load(self.tmpfile)
        self.assertEqual(ring.overload, 0.1)
        self.assertTrue('10.00%' in out)
        self.assertTrue('0.100000' in out)

    def test_set_overload_percent_strange_input(self):
        self.create_sample_ring()
        argv = "set_overload 26%%%%".split()
        out, err = self.run_srb(*argv)
        ring = RingBuilder.load(self.tmpfile)
        self.assertEqual(ring.overload, 0.26)
        self.assertTrue('26.00%' in out)
        self.assertTrue('0.260000' in out)

    def test_server_overload_crazy_high(self):
        self.create_sample_ring()
        argv = "set_overload 10".split()
        out, err = self.run_srb(*argv)
        ring = RingBuilder.load(self.tmpfile)
        self.assertEqual(ring.overload, 10.0)
        self.assertTrue('Warning overload is greater than 100%' in out)
        self.assertTrue('1000.00%' in out)
        self.assertTrue('10.000000' in out)
        # but it's cool if you do it on purpose
        argv[-1] = '1000%'
        out, err = self.run_srb(*argv)
        ring = RingBuilder.load(self.tmpfile)
        self.assertEqual(ring.overload, 10.0)
        self.assertTrue('Warning overload is greater than 100%' not in out)
        self.assertTrue('1000.00%' in out)
        self.assertTrue('10.000000' in out)

    def test_set_overload_number_of_arguments(self):
        self.create_sample_ring()
        # Test missing arguments
        argv = ["", self.tmpfile, "set_overload"]
        self.assertSystemExit(EXIT_ERROR, ringbuilder.main, argv)

    def test_set_replicas_number_of_arguments(self):
        self.create_sample_ring()
        # Test Number of arguments abnormal
        argv = ["", self.tmpfile, "set_replicas"]
        self.assertSystemExit(EXIT_ERROR, ringbuilder.main, argv)

    def test_set_replicas_invalid_value(self):
        self.create_sample_ring()
        # Test not a valid number
        argv = ["", self.tmpfile, "set_replicas", "test"]
        self.assertSystemExit(EXIT_ERROR, ringbuilder.main, argv)

        # Test new replicas is 0
        argv = ["", self.tmpfile, "set_replicas", "0"]
        self.assertSystemExit(EXIT_ERROR, ringbuilder.main, argv)

    def test_validate(self):
        self.create_sample_ring()
        ring = RingBuilder.load(self.tmpfile)
        ring.rebalance()
        ring.save(self.tmpfile)
        argv = ["", self.tmpfile, "validate"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)

    def test_validate_empty_file(self):
        open(self.tmpfile, 'a').close
        argv = ["", self.tmpfile, "validate"]
        self.assertSystemExit(EXIT_ERROR, ringbuilder.main, argv)

    def test_validate_corrupted_file(self):
        self.create_sample_ring()
        ring = RingBuilder.load(self.tmpfile)
        ring.rebalance()
        self.assertTrue(ring.validate())  # ring is valid until now
        ring.save(self.tmpfile)
        argv = ["", self.tmpfile, "validate"]

        # corrupt the file
        with open(self.tmpfile, 'wb') as f:
            f.write(os.urandom(1024))
        self.assertSystemExit(EXIT_ERROR, ringbuilder.main, argv)

    def test_validate_non_existent_file(self):
        rand_file = '%s/%s' % ('/tmp', str(uuid.uuid4()))
        argv = ["", rand_file, "validate"]
        self.assertSystemExit(EXIT_ERROR, ringbuilder.main, argv)

    def test_validate_non_accessible_file(self):
        with mock.patch.object(
                RingBuilder, 'load',
                mock.Mock(side_effect=exceptions.PermissionError)):
            argv = ["", self.tmpfile, "validate"]
            self.assertSystemExit(EXIT_ERROR, ringbuilder.main, argv)

    def test_validate_generic_error(self):
        with mock.patch.object(
                RingBuilder, 'load', mock.Mock(
                    side_effect=IOError('Generic error occurred'))):
            argv = ["", self.tmpfile, "validate"]
            self.assertSystemExit(EXIT_ERROR, ringbuilder.main, argv)

    def test_search_device_ipv4_old_format(self):
        self.create_sample_ring()
        # Test ipv4(old format)
        argv = ["", self.tmpfile, "search",
                "d0r0z0-127.0.0.1:6200R127.0.0.1:6200/sda1_some meta data"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)

    def test_search_device_ipv6_old_format(self):
        self.create_sample_ring()
        # add IPV6
        argv = \
            ["", self.tmpfile, "add",
             "--region", "2", "--zone", "3",
             "--ip", "[2001:0000:1234:0000:0000:C1C0:ABCD:0876]",
             "--port", "6200",
             "--replication-ip", "[2::10]",
             "--replication-port", "7000",
             "--device", "sda3", "--meta", "some meta data",
             "--weight", "3.14159265359"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)

        # write ring file
        ring = RingBuilder.load(self.tmpfile)
        ring.rebalance()
        ring.save(self.tmpfile)

        # Test ipv6(old format)
        argv = ["", self.tmpfile, "search",
                "d4r2z3-[2001:0000:1234:0000:0000:C1C0:ABCD:0876]:6200"
                "R[2::10]:7000/sda3_some meta data"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)

    def test_search_device_ipv4_new_format(self):
        self.create_sample_ring()
        # Test ipv4(new format)
        argv = \
            ["", self.tmpfile, "search",
             "--id", "0", "--region", "0", "--zone", "0",
             "--ip", "127.0.0.1",
             "--port", "6200",
             "--replication-ip", "127.0.0.1",
             "--replication-port", "6200",
             "--device", "sda1", "--meta", "some meta data"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)

    def test_search_device_ipv6_new_format(self):
        self.create_sample_ring()
        # add IPV6
        argv = \
            ["", self.tmpfile, "add",
             "--region", "2", "--zone", "3",
             "--ip", "[2001:0000:1234:0000:0000:C1C0:ABCD:0876]",
             "--port", "6200",
             "--replication-ip", "[2::10]",
             "--replication-port", "7000",
             "--device", "sda3", "--meta", "some meta data",
             "--weight", "3.14159265359"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)

        # write ring file
        ring = RingBuilder.load(self.tmpfile)
        ring.rebalance()
        ring.save(self.tmpfile)

        # Test ipv6(new format)
        argv = \
            ["", self.tmpfile, "search",
             "--id", "4", "--region", "2", "--zone", "3",
             "--ip", "[2001:0000:1234:0000:0000:C1C0:ABCD:0876]",
             "--port", "6200",
             "--replication-ip", "[2::10]",
             "--replication-port", "7000",
             "--device", "sda3", "--meta", "some meta data"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)

    def test_search_device_domain_new_format(self):
        self.create_sample_ring()
        # add domain name
        argv = \
            ["", self.tmpfile, "add",
             "--region", "2", "--zone", "3",
             "--ip", "test.test.com",
             "--port", "6200",
             "--replication-ip", "r.test.com",
             "--replication-port", "7000",
             "--device", "sda3", "--meta", "some meta data",
             "--weight", "3.14159265359"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)
        # write ring file
        ring = RingBuilder.load(self.tmpfile)
        ring.rebalance()
        ring.save(self.tmpfile)

        # Test domain name
        argv = \
            ["", self.tmpfile, "search",
             "--id", "4", "--region", "2", "--zone", "3",
             "--ip", "test.test.com",
             "--port", "6200",
             "--replication-ip", "r.test.com",
             "--replication-port", "7000",
             "--device", "sda3", "--meta", "some meta data"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)

    def test_search_device_number_of_arguments(self):
        self.create_sample_ring()
        # Test Number of arguments abnormal
        argv = ["", self.tmpfile, "search"]
        self.assertSystemExit(EXIT_ERROR, ringbuilder.main, argv)

    def test_search_device_no_matching(self):
        self.create_sample_ring()
        # Test No matching devices
        argv = ["", self.tmpfile, "search",
                "--ip", "unknown"]
        self.assertSystemExit(EXIT_ERROR, ringbuilder.main, argv)

    def test_list_parts_ipv4_old_format(self):
        self.create_sample_ring()
        ring = RingBuilder.load(self.tmpfile)
        ring.rebalance()
        ring.save(self.tmpfile)
        # Test ipv4(old format)
        argv = ["", self.tmpfile, "list_parts",
                "d0r0z0-127.0.0.1:6200R127.0.0.1:6200/sda1_some meta data"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)

    def test_list_parts_ipv6_old_format(self):
        self.create_sample_ring()
        # add IPV6
        argv = \
            ["", self.tmpfile, "add",
             "--region", "2", "--zone", "3",
             "--ip", "[2001:0000:1234:0000:0000:C1C0:ABCD:0876]",
             "--port", "6200",
             "--replication-ip", "[2::10]",
             "--replication-port", "7000",
             "--device", "sda3", "--meta", "some meta data",
             "--weight", "3.14159265359"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)

        # write ring file
        ring = RingBuilder.load(self.tmpfile)
        ring.rebalance()
        ring.save(self.tmpfile)

        # Test ipv6(old format)
        argv = ["", self.tmpfile, "list_parts",
                "d4r2z3-[2001:0000:1234:0000:0000:C1C0:ABCD:0876]:6200"
                "R[2::10]:7000/sda3_some meta data"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)

    def test_list_parts_ipv4_new_format(self):
        self.create_sample_ring()
        ring = RingBuilder.load(self.tmpfile)
        ring.rebalance()
        ring.save(self.tmpfile)
        # Test ipv4(new format)
        argv = \
            ["", self.tmpfile, "list_parts",
             "--id", "0", "--region", "0", "--zone", "0",
             "--ip", "127.0.0.1",
             "--port", "6200",
             "--replication-ip", "127.0.0.1",
             "--replication-port", "6200",
             "--device", "sda1", "--meta", "some meta data"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)

    def test_list_parts_ipv6_new_format(self):
        self.create_sample_ring()
        # add IPV6
        argv = \
            ["", self.tmpfile, "add",
             "--region", "2", "--zone", "3",
             "--ip", "[2001:0000:1234:0000:0000:C1C0:ABCD:0876]",
             "--port", "6200",
             "--replication-ip", "[2::10]",
             "--replication-port", "7000",
             "--device", "sda3", "--meta", "some meta data",
             "--weight", "3.14159265359"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)

        # write ring file
        ring = RingBuilder.load(self.tmpfile)
        ring.rebalance()
        ring.save(self.tmpfile)

        # Test ipv6(new format)
        argv = \
            ["", self.tmpfile, "list_parts",
             "--id", "4", "--region", "2", "--zone", "3",
             "--ip", "[2001:0000:1234:0000:0000:C1C0:ABCD:0876]",
             "--port", "6200",
             "--replication-ip", "[2::10]",
             "--replication-port", "7000",
             "--device", "sda3", "--meta", "some meta data"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)

    def test_list_parts_domain_new_format(self):
        self.create_sample_ring()
        # add domain name
        argv = \
            ["", self.tmpfile, "add",
             "--region", "2", "--zone", "3",
             "--ip", "test.test.com",
             "--port", "6200",
             "--replication-ip", "r.test.com",
             "--replication-port", "7000",
             "--device", "sda3", "--meta", "some meta data",
             "--weight", "3.14159265359"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)

        # write ring file
        ring = RingBuilder.load(self.tmpfile)
        ring.rebalance()
        ring.save(self.tmpfile)

        # Test domain name
        argv = \
            ["", self.tmpfile, "list_parts",
             "--id", "4", "--region", "2", "--zone", "3",
             "--ip", "test.test.com",
             "--port", "6200",
             "--replication-ip", "r.test.com",
             "--replication-port", "7000",
             "--device", "sda3", "--meta", "some meta data"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)

    def test_list_parts_number_of_arguments(self):
        self.create_sample_ring()
        # Test Number of arguments abnormal
        argv = ["", self.tmpfile, "list_parts"]
        self.assertSystemExit(EXIT_ERROR, ringbuilder.main, argv)

    def test_list_parts_no_matching(self):
        self.create_sample_ring()
        # Test No matching devices
        argv = ["", self.tmpfile, "list_parts",
                "--ip", "unknown"]
        self.assertSystemExit(EXIT_ERROR, ringbuilder.main, argv)

    def test_unknown(self):
        self.create_sample_ring()
        argv = ["", self.tmpfile, "unknown"]
        self.assertSystemExit(EXIT_ERROR, ringbuilder.main, argv)

    def test_default(self):
        self.create_sample_ring()
        argv = ["", self.tmpfile]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)

    def test_default_show_removed(self):
        mock_stdout = six.StringIO()
        mock_stderr = six.StringIO()

        self.create_sample_ring()

        # Note: it also sets device's weight to zero.
        argv = ["", self.tmpfile, "remove", "--id", "1"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)

        # Setting another device's weight to zero to be sure we distinguish
        # real removed device and device with zero weight.
        argv = ["", self.tmpfile, "set_weight", "0", "--id", "3"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)

        argv = ["", self.tmpfile]
        with mock.patch("sys.stdout", mock_stdout):
            with mock.patch("sys.stderr", mock_stderr):
                self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)

        expected = "%s, build version 6\n" \
            "64 partitions, 3.000000 replicas, 4 regions, 4 zones, " \
            "4 devices, 100.00 balance, 0.00 dispersion\n" \
            "The minimum number of hours before a partition can be " \
            "reassigned is 1 (0:00:00 remaining)\n" \
            "The overload factor is 0.00%% (0.000000)\n" \
            "Ring file %s.ring.gz not found, probably " \
            "it hasn't been written yet\n" \
            "Devices:    id  region  zone      ip address  port  " \
            "replication ip  replication port      name weight " \
            "partitions balance flags meta\n" \
            "             0       0     0       127.0.0.1  6200       " \
            "127.0.0.1              6200      sda1 100.00" \
            "          0 -100.00       some meta data\n" \
            "             1       1     1       127.0.0.2  6201       " \
            "127.0.0.2              6201      sda2   0.00" \
            "          0    0.00   DEL \n" \
            "             2       2     2       127.0.0.3  6202       " \
            "127.0.0.3              6202      sdc3 100.00" \
            "          0 -100.00       \n" \
            "             3       3     3       127.0.0.4  6203       " \
            "127.0.0.4              6203      sdd4   0.00" \
            "          0    0.00       \n" % (self.tmpfile, self.tmpfile)
        self.assertEqual(expected, mock_stdout.getvalue())

    def test_default_ringfile_check(self):
        self.create_sample_ring()

        # ring file not created
        mock_stdout = six.StringIO()
        mock_stderr = six.StringIO()
        argv = ["", self.tmpfile]
        with mock.patch("sys.stdout", mock_stdout):
            with mock.patch("sys.stderr", mock_stderr):
                self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)
        ring_not_found_re = re.compile("Ring file .*\.ring\.gz not found")
        self.assertTrue(ring_not_found_re.findall(mock_stdout.getvalue()))

        # write ring file
        argv = ["", self.tmpfile, "rebalance"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)
        # ring file is up-to-date
        mock_stdout = six.StringIO()
        argv = ["", self.tmpfile]
        with mock.patch("sys.stdout", mock_stdout):
            with mock.patch("sys.stderr", mock_stderr):
                self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)
        ring_up_to_date_re = re.compile("Ring file .*\.ring\.gz is up-to-date")
        self.assertTrue(ring_up_to_date_re.findall(mock_stdout.getvalue()))

        # change builder (set weight)
        argv = ["", self.tmpfile, "set_weight", "0", "--id", "3"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)
        # ring file is obsolete after set_weight
        mock_stdout = six.StringIO()
        argv = ["", self.tmpfile]
        with mock.patch("sys.stdout", mock_stdout):
            with mock.patch("sys.stderr", mock_stderr):
                self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)
        ring_obsolete_re = re.compile("Ring file .*\.ring\.gz is obsolete")
        self.assertTrue(ring_obsolete_re.findall(mock_stdout.getvalue()))

        # write ring file
        argv = ["", self.tmpfile, "write_ring"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)
        # ring file up-to-date again
        mock_stdout = six.StringIO()
        argv = ["", self.tmpfile]
        with mock.patch("sys.stdout", mock_stdout):
            with mock.patch("sys.stderr", mock_stderr):
                self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)
        self.assertTrue(ring_up_to_date_re.findall(mock_stdout.getvalue()))

        # Break ring file e.g. just make it empty
        open('%s.ring.gz' % self.tmpfile, 'w').close()
        # ring file is invalid
        mock_stdout = six.StringIO()
        argv = ["", self.tmpfile]
        with mock.patch("sys.stdout", mock_stdout):
            with mock.patch("sys.stderr", mock_stderr):
                self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)
        ring_invalid_re = re.compile("Ring file .*\.ring\.gz is invalid")
        self.assertTrue(ring_invalid_re.findall(mock_stdout.getvalue()))

    def test_rebalance(self):
        self.create_sample_ring()
        argv = ["", self.tmpfile, "rebalance", "3"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)
        ring = RingBuilder.load(self.tmpfile)
        self.assertTrue(ring.validate())

    def test_rebalance_no_device_change(self):
        self.create_sample_ring()
        ring = RingBuilder.load(self.tmpfile)
        ring.rebalance()
        ring.save(self.tmpfile)
        # Test No change to the device
        argv = ["", self.tmpfile, "rebalance", "3"]
        self.assertSystemExit(EXIT_WARNING, ringbuilder.main, argv)

    def test_rebalance_no_devices(self):
        # Test no devices
        argv = ["", self.tmpfile, "create", "6", "3.14159265359", "1"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)
        argv = ["", self.tmpfile, "rebalance"]
        self.assertSystemExit(EXIT_ERROR, ringbuilder.main, argv)

    def test_rebalance_remove_zero_weighted_device(self):
        self.create_sample_ring()
        ring = RingBuilder.load(self.tmpfile)
        ring.set_dev_weight(3, 0.0)
        ring.rebalance()
        ring.pretend_min_part_hours_passed()
        ring.remove_dev(3)
        ring.save(self.tmpfile)

        # Test rebalance after remove 0 weighted device
        argv = ["", self.tmpfile, "rebalance", "3"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)
        ring = RingBuilder.load(self.tmpfile)
        self.assertTrue(ring.validate())
        self.assertEqual(ring.devs[3], None)

    def test_rebalance_resets_time_remaining(self):
        self.create_sample_ring()
        ring = RingBuilder.load(self.tmpfile)

        time_path = 'swift.common.ring.builder.time'
        argv = ["", self.tmpfile, "rebalance", "3"]
        time = 0

        # first rebalance, should have 1 hour left before next rebalance
        time += 3600
        with mock.patch(time_path, return_value=time):
            self.assertEqual(ring.min_part_seconds_left, 0)
            self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)
            ring = RingBuilder.load(self.tmpfile)
            self.assertEqual(ring.min_part_seconds_left, 3600)

        # min part hours passed, change ring and save for rebalance
        ring.set_dev_weight(0, ring.devs[0]['weight'] * 2)
        ring.save(self.tmpfile)

        # second rebalance, should have 1 hour left
        time += 3600
        with mock.patch(time_path, return_value=time):
            self.assertEqual(ring.min_part_seconds_left, 0)
            self.assertSystemExit(EXIT_WARNING, ringbuilder.main, argv)
            ring = RingBuilder.load(self.tmpfile)
            self.assertTrue(ring.min_part_seconds_left, 3600)

    def test_rebalance_failure_does_not_reset_last_moves_epoch(self):
        ring = RingBuilder(8, 3, 1)
        ring.add_dev({'id': 0, 'region': 0, 'zone': 0, 'weight': 1,
                      'ip': '127.0.0.1', 'port': 6010, 'device': 'sda1'})
        ring.add_dev({'id': 1, 'region': 0, 'zone': 0, 'weight': 1,
                      'ip': '127.0.0.1', 'port': 6020, 'device': 'sdb1'})
        ring.add_dev({'id': 2, 'region': 0, 'zone': 0, 'weight': 1,
                      'ip': '127.0.0.1', 'port': 6030, 'device': 'sdc1'})

        time_path = 'swift.common.ring.builder.time'
        argv = ["", self.tmpfile, "rebalance", "3"]

        with mock.patch(time_path, return_value=0):
            ring.rebalance()
        ring.save(self.tmpfile)

        # min part hours not passed
        with mock.patch(time_path, return_value=(3600 * 0.6)):
            self.assertSystemExit(EXIT_WARNING, ringbuilder.main, argv)
            ring = RingBuilder.load(self.tmpfile)
            self.assertEqual(ring.min_part_seconds_left, 3600 * 0.4)

        ring.save(self.tmpfile)

        # min part hours passed, no partitions need to be moved
        with mock.patch(time_path, return_value=(3600 * 1.5)):
            self.assertSystemExit(EXIT_WARNING, ringbuilder.main, argv)
            ring = RingBuilder.load(self.tmpfile)
            self.assertEqual(ring.min_part_seconds_left, 0)

    def test_rebalance_with_seed(self):
        self.create_sample_ring()
        # Test rebalance using explicit seed parameter
        argv = ["", self.tmpfile, "rebalance", "--seed", "2"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)

    def test_write_ring(self):
        self.create_sample_ring()
        argv = ["", self.tmpfile, "rebalance"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)

        argv = ["", self.tmpfile, "write_ring"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)

    def test_write_builder(self):
        # Test builder file already exists
        self.create_sample_ring()
        argv = ["", self.tmpfile, "rebalance"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)
        argv = ["", self.tmpfile, "write_builder"]
        exp_results = {'valid_exit_codes': [2]}
        self.run_srb(*argv, exp_results=exp_results)

    def test_write_builder_after_device_removal(self):
        # Test regenerating builder file after having removed a device
        # and lost the builder file
        self.create_sample_ring()

        argv = ["", self.tmpfile, "add", "r1z1-127.0.0.1:6200/sdb", "1.0"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)
        argv = ["", self.tmpfile, "add", "r1z1-127.0.0.1:6200/sdc", "1.0"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)
        argv = ["", self.tmpfile, "rebalance"]
        self.assertSystemExit(EXIT_WARNING, ringbuilder.main, argv)

        argv = ["", self.tmpfile, "remove", "--id", "0"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)
        argv = ["", self.tmpfile, "rebalance"]
        self.assertSystemExit(EXIT_WARNING, ringbuilder.main, argv)

        backup_file = os.path.join(os.path.dirname(self.tmpfile),
                                   os.path.basename(self.tmpfile) + ".ring.gz")
        os.remove(self.tmpfile)  # loses file...

        argv = ["", backup_file, "write_builder", "24"]
        self.assertEqual(ringbuilder.main(argv), None)

    def test_warn_at_risk(self):
        # when the number of total part replicas (3 * 2 ** 4 = 48 in
        # this ring) is less than the total units of weight (310 in this
        # ring) the relative number of parts per unit of weight (called
        # weight_of_one_part) is less than 1 - and each whole part
        # placed takes up a larger ratio of the fractional number of
        # parts the device wants - so it's much more difficult to
        # satisfy a device's weight exactly - that is to say less parts
        # to go around tends to make things lumpy
        self.create_sample_ring(4)
        ring = RingBuilder.load(self.tmpfile)
        ring.devs[0]['weight'] = 10
        ring.save(self.tmpfile)
        argv = ["", self.tmpfile, "rebalance"]
        self.assertSystemExit(EXIT_WARNING, ringbuilder.main, argv)

    def test_no_warn_when_balanced(self):
        # when the number of total part replicas (3 * 2 ** 10 = 3072 in
        # this ring) is larger than the total units of weight (310 in
        # this ring) the relative number of parts per unit of weight
        # (called weight_of_one_part) is more than 1 - and each whole
        # part placed takes up a smaller ratio of the larger number of
        # parts the device wants - so it's much easier to satisfy a
        # device's weight exactly - that is to say more parts to go
        # around tends to smooth things out
        self.create_sample_ring(10)
        ring = RingBuilder.load(self.tmpfile)
        ring.devs[0]['weight'] = 10
        ring.save(self.tmpfile)
        argv = ["", self.tmpfile, "rebalance"]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)

    def test_invalid_device_name(self):
        self.create_sample_ring()
        for device_name in ["", " ", " sda1", "sda1 ", " meta "]:

            argv = ["",
                    self.tmpfile,
                    "add",
                    "r1z1-127.0.0.1:6200/%s" % device_name,
                    "1"]
            self.assertSystemExit(EXIT_ERROR, ringbuilder.main, argv)

            argv = ["",
                    self.tmpfile,
                    "add",
                    "--region", "1",
                    "--zone", "1",
                    "--ip", "127.0.0.1",
                    "--port", "6200",
                    "--device", device_name,
                    "--weight", "100"]
            self.assertSystemExit(EXIT_ERROR, ringbuilder.main, argv)

    def test_dispersion_command(self):
        self.create_sample_ring()
        self.run_srb('rebalance')
        out, err = self.run_srb('dispersion -v')
        self.assertIn('dispersion', out.lower())
        self.assertFalse(err)

    def test_use_ringfile_as_builderfile(self):
        mock_stdout = six.StringIO()
        mock_stderr = six.StringIO()

        argv = ["", "object.ring.gz"]

        with mock.patch("sys.stdout", mock_stdout):
            with mock.patch("sys.stderr", mock_stderr):
                self.assertSystemExit(EXIT_ERROR, ringbuilder.main, argv)
        expected = "Note: using object.builder instead of object.ring.gz " \
            "as builder file\n" \
            "Ring Builder file does not exist: object.builder\n"
        self.assertEqual(expected, mock_stdout.getvalue())

    def test_main_no_arguments(self):
        # Test calling main with no arguments
        argv = []
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)

    def test_main_single_argument(self):
        # Test calling main with single argument
        argv = [""]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)

    def test_main_with_safe(self):
        # Test calling main with '-safe' argument
        self.create_sample_ring()
        argv = ["-safe", self.tmpfile]
        self.assertSystemExit(EXIT_SUCCESS, ringbuilder.main, argv)


class TestRebalanceCommand(unittest.TestCase, RunSwiftRingBuilderMixin):

    def __init__(self, *args, **kwargs):
        super(TestRebalanceCommand, self).__init__(*args, **kwargs)

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        tmpf = tempfile.NamedTemporaryFile(dir=self.tmpdir)
        self.tempfile = self.tmpfile = tmpf.name

    def tearDown(self):
        try:
            shutil.rmtree(self.tmpdir, True)
        except OSError:
            pass

    def run_srb(self, *argv):
        mock_stdout = six.StringIO()
        mock_stderr = six.StringIO()

        srb_args = ["", self.tempfile] + [str(s) for s in argv]

        try:
            with mock.patch("sys.stdout", mock_stdout):
                with mock.patch("sys.stderr", mock_stderr):
                    ringbuilder.main(srb_args)
        except SystemExit as err:
            if err.code not in (0, 1):  # (success, warning)
                raise
        return (mock_stdout.getvalue(), mock_stderr.getvalue())

    def test_debug(self):
        # NB: getLogger(name) always returns the same object
        rb_logger = logging.getLogger("swift.ring.builder")
        try:
            self.assertNotEqual(rb_logger.getEffectiveLevel(), logging.DEBUG)

            self.run_srb("create", 8, 3, 1)
            self.run_srb("add",
                         "r1z1-10.1.1.1:2345/sda", 100.0,
                         "r1z1-10.1.1.1:2345/sdb", 100.0,
                         "r1z1-10.1.1.1:2345/sdc", 100.0,
                         "r1z1-10.1.1.1:2345/sdd", 100.0)
            self.run_srb("rebalance", "--debug")
            self.assertEqual(rb_logger.getEffectiveLevel(), logging.DEBUG)

            rb_logger.setLevel(logging.INFO)
            self.run_srb("rebalance", "--debug", "123")
            self.assertEqual(rb_logger.getEffectiveLevel(), logging.DEBUG)

            rb_logger.setLevel(logging.INFO)
            self.run_srb("rebalance", "123", "--debug")
            self.assertEqual(rb_logger.getEffectiveLevel(), logging.DEBUG)

        finally:
            rb_logger.setLevel(logging.INFO)  # silence other test cases

    def test_rebalance_warning_appears(self):
        self.run_srb("create", 8, 3, 24)
        # all in one machine: totally balanceable
        self.run_srb("add",
                     "r1z1-10.1.1.1:2345/sda", 100.0,
                     "r1z1-10.1.1.1:2345/sdb", 100.0,
                     "r1z1-10.1.1.1:2345/sdc", 100.0,
                     "r1z1-10.1.1.1:2345/sdd", 100.0)
        out, err = self.run_srb("rebalance")
        self.assertTrue("rebalance/repush" not in out)

        # 2 machines of equal size: balanceable, but not in one pass due to
        # min_part_hours > 0
        self.run_srb("add",
                     "r1z1-10.1.1.2:2345/sda", 100.0,
                     "r1z1-10.1.1.2:2345/sdb", 100.0,
                     "r1z1-10.1.1.2:2345/sdc", 100.0,
                     "r1z1-10.1.1.2:2345/sdd", 100.0)
        self.run_srb("pretend_min_part_hours_passed")
        out, err = self.run_srb("rebalance")
        self.assertTrue("rebalance/repush" in out)

        # after two passes, it's all balanced out
        self.run_srb("pretend_min_part_hours_passed")
        out, err = self.run_srb("rebalance")
        self.assertTrue("rebalance/repush" not in out)

    def test_rebalance_warning_with_overload(self):
        self.run_srb("create", 8, 3, 24)
        self.run_srb("set_overload", 0.12)
        # The ring's balance is at least 5, so normally we'd get a warning,
        # but it's suppressed due to the overload factor.
        self.run_srb("add",
                     "r1z1-10.1.1.1:2345/sda", 100.0,
                     "r1z1-10.1.1.1:2345/sdb", 100.0,
                     "r1z1-10.1.1.1:2345/sdc", 120.0)
        out, err = self.run_srb("rebalance")
        self.assertTrue("rebalance/repush" not in out)

        # Now we add in a really big device, but not enough partitions move
        # to fill it in one pass, so we see the rebalance warning.
        self.run_srb("add", "r1z1-10.1.1.1:2345/sdd", 99999.0)
        self.run_srb("pretend_min_part_hours_passed")
        out, err = self.run_srb("rebalance")
        self.assertTrue("rebalance/repush" in out)

    def test_cached_dispersion_value(self):
        self.run_srb("create", 8, 3, 24)
        self.run_srb("add",
                     "r1z1-10.1.1.1:2345/sda", 100.0,
                     "r1z1-10.1.1.1:2345/sdb", 100.0,
                     "r1z1-10.1.1.1:2345/sdc", 100.0,
                     "r1z1-10.1.1.1:2345/sdd", 100.0)
        self.run_srb('rebalance')
        out, err = self.run_srb()  # list devices
        self.assertTrue('dispersion' in out)
        # remove cached dispersion value
        builder = RingBuilder.load(self.tempfile)
        builder.dispersion = None
        builder.save(self.tempfile)
        # now dispersion output is suppressed
        out, err = self.run_srb()  # list devices
        self.assertFalse('dispersion' in out)
        # but will show up after rebalance
        self.run_srb('rebalance', '-f')
        out, err = self.run_srb()  # list devices
        self.assertTrue('dispersion' in out)


if __name__ == '__main__':
    unittest.main()