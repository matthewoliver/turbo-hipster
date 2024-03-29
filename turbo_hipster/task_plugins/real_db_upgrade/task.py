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


import json
import logging
import os
import re

from turbo_hipster.lib import common
from turbo_hipster.lib import models
from turbo_hipster.lib import utils


import turbo_hipster.task_plugins.real_db_upgrade.handle_results\
    as handle_results


# Regex for log checking
MIGRATION_START_RE = re.compile('([0-9]+) -&gt; ([0-9]+)\.\.\.$')
MIGRATION_END_RE = re.compile('^done$')


class Runner(models.ShellTask):

    """ This thread handles the actual sql-migration tests.
        It pulls in a gearman job from the  build:real-db-upgrade
        queue and runs it through _handle_patchset"""

    log = logging.getLogger("task_plugins.real_db_upgrade.task.Runner")

    def __init__(self, worker_server, plugin_config, job_name):
        super(Runner, self).__init__(worker_server, plugin_config, job_name)

        # Set up the runner worker
        self.datasets = []
        self.job_datasets = []

        # Define the number of steps we will do to determine our progress.
        self.total_steps += 1

    def do_job_steps(self):
        # Step 1: Figure out which datasets to run
        self.job_datasets = self._get_job_datasets()

        # all other steps are common to running a shell script
        super(Runner, self).do_job_steps()

    @common.task_step
    def _get_job_datasets(self):
        """ Take the applicable datasets for this job and set them up in
        self.job_datasets """

        job_datasets = []
        for dataset in self._get_datasets():
            # Only load a dataset if it is the right project and we
            # know how to process the upgrade
            if (self.job_arguments['ZUUL_PROJECT'] ==
                    dataset['config']['project'] and
                    self._get_project_command(dataset['config']['type'])):
                dataset['determined_path'] = utils.determine_job_identifier(
                    self.job_arguments, self.plugin_config['function'],
                    self.job.unique
                )
                dataset['job_log_file_path'] = os.path.join(
                    self.worker_server.config['jobs_working_dir'],
                    dataset['determined_path'],
                    dataset['name'] + '.log'
                )
                dataset['result'] = 'UNTESTED'
                dataset['command'] = \
                    self._get_project_command(dataset['config']['type'])

                job_datasets.append(dataset)

        return job_datasets

    @common.task_step
    def _execute_script(self):
        # Run script
        self.script_return_code = self._execute_migrations()

    @common.task_step
    def _parse_and_check_results(self):
        super(Runner, self)._parse_and_check_results()
        self._check_all_dataset_logs_for_errors()

    @common.task_step
    def _handle_results(self):
        """ pass over the results to handle_results.py for post-processing """
        self.log.debug("Process the resulting files (upload/push)")
        index_url = handle_results.generate_push_results(
            self.job_datasets,
            self.worker_server.config['publish_logs']
        )
        self.log.debug("Index URL found at %s" % index_url)
        self.work_data['url'] = index_url

    def _check_all_dataset_logs_for_errors(self):
        self.log.debug('Check logs for errors')

        for i, dataset in enumerate(self.job_datasets):
            success, messages = handle_results.check_log_file(
                dataset['job_log_file_path'], self.git_path, dataset)

            if self.success and not success:
                self.success = False
            for message in messages:
                self.messages.append(message)

            if success:
                self.job_datasets[i]['result'] = 'SUCCESS'
            else:
                self.job_datasets[i]['result'] = messages[0]

    def _get_datasets(self):
        self.log.debug("Get configured datasets to run tests against")
        if len(self.datasets) > 0:
            return self.datasets

        datasets_path = self.plugin_config['datasets_dir']
        for ent in os.listdir(datasets_path):
            dataset_dir = os.path.join(datasets_path, ent)
            if (os.path.isdir(dataset_dir) and os.path.isfile(
                    os.path.join(dataset_dir, 'config.json'))):
                dataset = {}
                with open(os.path.join(dataset_dir, 'config.json'),
                          'r') as config_stream:
                    dataset_config = json.load(config_stream)

                    dataset['name'] = ent
                    dataset['dataset_dir'] = dataset_dir
                    dataset['config'] = dataset_config

                    self.datasets.append(dataset)

        return self.datasets

    def _get_project_command(self, db_type):
        command = (self.job_arguments['ZUUL_PROJECT'].split('/')[-1] + '_' +
                   db_type + '_migrations.sh')
        command = os.path.join(os.path.dirname(__file__), command)
        if os.path.isfile(command):
            return command
        return False

    def _execute_migrations(self):
        """ Execute the migration on each dataset in datasets """

        self.log.debug("Run the db sync upgrade script")

        for dataset in self.job_datasets:
            cmd = dataset['command']
            # $1 is the unique id
            # $2 is the working dir path
            # $3 is the path to the git repo path
            # $4 is the db user
            # $5 is the db password
            # $6 is the db name
            # $7 is the path to the dataset to test against
            # $8 is the logging.conf for openstack
            # $9 is the pip cache dir

            cmd += (
                (' %(unique_id)s %(job_working_dir)s %(git_path)s'
                    ' %(dbuser)s %(dbpassword)s %(db)s'
                    ' %(dataset_path)s %(logging_conf)s %(pip_cache_dir)s')
                % {
                    'unique_id': self.job.unique,
                    'job_working_dir': os.path.join(
                        self.worker_server.config['jobs_working_dir'],
                        dataset['determined_path']
                    ),
                    'git_path': self.git_path,
                    'dbuser': dataset['config']['db_user'],
                    'dbpassword': dataset['config']['db_pass'],
                    'db': dataset['config']['database'],
                    'dataset_path': os.path.join(
                        dataset['dataset_dir'],
                        dataset['config']['seed_data']
                    ),
                    'logging_conf': os.path.join(
                        dataset['dataset_dir'],
                        dataset['config']['logging_conf']
                    ),
                    'pip_cache_dir':
                    self.worker_server.config['pip_download_cache']
                }
            )

            # Gather logs to watch
            syslog = '/var/log/syslog'
            sqlslo = '/var/log/mysql/slow-queries.log'
            sqlerr = '/var/log/mysql/error.log'
            if 'logs' in self.worker_server.config:
                if 'syslog' in self.worker_server.config['logs']:
                    syslog = self.worker_server.config['logs']['syslog']
                if 'sqlslo' in self.worker_server.config['logs']:
                    sqlslo = self.worker_server.config['logs']['sqlslo']
                if 'sqlerr' in self.worker_server.config['logs']:
                    sqlerr = self.worker_server.config['logs']['sqlerr']

            rc = utils.execute_to_log(
                cmd,
                dataset['job_log_file_path'],
                watch_logs=[
                    ('[syslog]', syslog),
                    ('[sqlslo]', sqlslo),
                    ('[sqlerr]', sqlerr)
                ],
            )
            # FIXME: If more than one dataset is provided we won't actually
            # test them!
            return rc
