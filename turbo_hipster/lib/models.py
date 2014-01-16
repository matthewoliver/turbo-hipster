# Copyright 2013 Rackspace Australia
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.


import copy
import json
import logging
import os

from turbo_hipster.lib import common
from turbo_hipster.lib import utils


class Task(object):

    log = logging.getLogger("lib.models.Task")

    def __init__(self, global_config, plugin_config, job_name):
        self.global_config = global_config
        self.plugin_config = plugin_config
        self.job_name = job_name

        self.job = None
        self.job_arguments = None
        self.work_data = None
        self.cancelled = False

        # Define the number of steps we will do to determine our progress.
        self.current_step = 0
        self.total_steps = 0

    def stop_worker(self, number):
        # Check the number is for this job instance
        # (makes it possible to run multiple workers with this task
        # on this server)
        if number == self.job.unique:
            self.log.debug("We've been asked to stop by our gearman manager")
            self.cancelled = True
            # TODO: Work out how to kill current step

    @common.task_step
    def _grab_patchset(self, job_args, job_log_file_path):
        """ Checkout the reference into config['git_working_dir'] """

        self.log.debug("Grab the patchset we want to test against")
        local_path = os.path.join(self.global_config['git_working_dir'],
                                  self.job_name, job_args['ZUUL_PROJECT'])
        if not os.path.exists(local_path):
            os.makedirs(local_path)

        git_args = copy.deepcopy(job_args)
        git_args['GIT_ORIGIN'] = 'git://git.openstack.org/'

        cmd = os.path.join(os.path.join(os.path.dirname(__file__),
                                        'gerrit-git-prep.sh'))
        cmd += ' https://review.openstack.org'
        cmd += ' http://zuul.rcbops.com'
        utils.execute_to_log(cmd, job_log_file_path, env=git_args,
                             cwd=local_path)
        return local_path

    def _get_work_data(self):
        if self.work_data is None:
            hostname = os.uname()[1]
            self.work_data = dict(
                name=self.job_name,
                number=self.job.unique,
                manager='turbo-hipster-manager-%s' % hostname,
                url='http://localhost',
            )
        return self.work_data

    def _send_work_data(self):
        """ Send the WORK DATA in json format for job """
        self.log.debug("Send the work data response: %s" %
                       json.dumps(self._get_work_data()))
        self.job.sendWorkData(json.dumps(self._get_work_data()))

    def _do_next_step(self):
        """ Send a WORK_STATUS command to the gearman server.
        This can provide a progress bar. """

        # Each opportunity we should check if we need to stop
        if self.cancelled:
            self.work_data['result'] = "Failed: Job cancelled"
            self.job.sendWorkStatus(self.current_step, self.total_steps)
            self.job.sendWorkFail()
            raise Exception('Job cancelled')

        self.current_step += 1
        self.job.sendWorkStatus(self.current_step, self.total_steps)


class ShellTask(Task):
    log = logging.getLogger("lib.models.ShellTask")

    def __init__(self, global_config, plugin_config, job_name):
        super(ShellTask, self).__init__(global_config, plugin_config, job_name)
        # Define the number of steps we will do to determine our progress.
        self.total_steps = 4

    def start_job(self, job):
        self.job = job
        self.success = True
        self.messages = []

        if self.job is not None:
            try:
                self.job_arguments = \
                    json.loads(self.job.arguments.decode('utf-8'))
                self.log.debug("Got job from ZUUL %s" % self.job_arguments)

                # Send an initial WORK_DATA and WORK_STATUS packets
                self._send_work_data()

                # Step 1: Checkout updates from git!
                self.git_path = self._grab_patchset(
                    self.job_arguments,
                    self.job_datasets[0]['job_log_file_path'])

                # Step 3: execute shell script
                # TODO

                # Step 4: Analyse logs for errors
                # TODO

                # Step 5: handle the results (and upload etc)
                # TODO

                # Finally, send updated work data and completed packets
                self._send_work_data()

                if self.work_data['result'] is 'SUCCESS':
                    self.job.sendWorkComplete(
                        json.dumps(self._get_work_data()))
                else:
                    self.job.sendWorkFail()
            except Exception as e:
                self.log.exception('Exception handling log event.')
                if not self.cancelled:
                    self.job.sendWorkException(str(e).encode('utf-8'))