import logging
import argparse
import socket
import sys
import traceback
from logging import handlers

from .datacontainer import DataContainer

class SampleProbe(object):

    __version__ = '0.2.0'
    # Mapping between zabbix-agent Debug option & logging level
    LOG_LEVEL = [
        logging.NOTSET,
        logging.CRITICAL,
        logging.ERROR,
        logging.INFO,
        logging.DEBUG,
        logging.DEBUG,
    ]
    logger = None
    probe_config = None
    hostname = None
    options = None

    def _parse_args(self, args):
        # Parse the script arguments
        parser = argparse.ArgumentParser(
            usage='%(prog)s [options]',
            description = 'A Protobix probe to monitor XXX with Zabbix',
            epilog = 'Protobix - copyright 2016 - Jean Baptiste Favre (www.jbfavre.org)'
        )
        # Probe operation mode
        probe_mode = parser.add_argument_group('Probe commands')
        probe_mode.add_argument(
            '--update-items', action = 'store_true',
            dest = 'update', default = False,
            help = 'Get & send items to Zabbix. This is the default '
                'behaviour even if option is not specified'
        )
        probe_mode.add_argument(
            '--discovery', action = 'store_true',
            dest = 'discovery', default = False,
            help = 'If specified, will perform Zabbix Low Level '
                'Discovery on Hadoop Cloudera Manager API. '
                'Default is to get & send items'
        )
        # Common options
        common = parser.add_argument_group('Common options')
        common.add_argument(
            '-c', '--config', dest = 'config_file',
            help='Probe config file location. Can be either absolute or relative path'
        )
        common.add_argument(
            '-d', '--dryrun', action = 'store_true', default = False,
            help='Do not send anything to Zabbix. Usefull to debug with --debug option'
        )
        common.add_argument(
            '-D', '--debug', action = 'store_true', default = False,
            help='Enable debug mode. This will prevent bulk send '
                'operations and force sending items one after the '
                'other, displaying result for each one'
        )
        # Zabbix specific options
        zabbix = parser.add_argument_group('Zabbix specific options')
        zabbix.add_argument(
            '-z', '--zabbix-server', default = '127.0.0.1',
            help = 'The hostname of Zabbix server or '
                'proxy, default is 127.0.0.1.'
        )
        zabbix.add_argument(
            '-p', '--zabbix-port', default = 10051, type = int,
            help = 'The port on which the Zabbix server or '
                'proxy is running, default is 10051'
        )
        # Probe specific options
        parser = self._parse_probe_args(parser)
        return parser.parse_args(args)

    def _setup_logging(self, zbx_container):
        logger = logging.getLogger(self.__class__.__name__)
        common_log_format = '[%(name)s:%(levelname)s] %(message)s'
        # Enable log like Zabbix Agent does
        # Though, when we have a tty, it's convenient to use console to log
        if zbx_container.log_type == 'console' or sys.stdout.isatty():
            consoleHandler = logging.StreamHandler()
            consoleFormatter = logging.Formatter(
                fmt = common_log_format,
                datefmt = '%Y%m%d:%H%M%S'
            )
            consoleHandler.setFormatter(consoleFormatter)
            logger.addHandler(consoleHandler)
        if zbx_container.log_type == 'file':
            print ('fichier')
            try:
                fileHandler = logging.FileHandler(zbx_container.log_file)
                # Use same date format as Zabbix: when logging into
                # zabbix_agentd log file, it's easier to read & parse
                logFormatter = logging.Formatter(
                    fmt = '%(process)d:%(asctime)s.%(msecs)03d ' + common_log_format,
                    datefmt = '%Y%m%d:%H%M%S'
                )
                fileHandler.setFormatter(logFormatter)
                logger.addHandler(fileHandler)
            except IOError:
                pass
        if zbx_container.log_type == 'system':
            print ('syslog')
            syslogHandler = logging.handlers.SysLogHandler(
                address = '/dev/log',
                facility = logging.handlers.SysLogHandler.LOG_DAEMON
            )
            # Use same date format as Zabbix does: when logging into
            # zabbix_agentd log file, it's easier to read & parse
            logFormatter = logging.Formatter(
                fmt = '%(process)d:%(asctime)s.%(msecs)03d ' + common_log_format,
                datefmt = '%Y%m%d:%H%M%S'
            )
            syslogHandler.setFormatter(logFormatter)
            logger.addHandler(syslogHandler)
        logger.setLevel(
            self.LOG_LEVEL[zbx_container.log_level]
        )
        return logger

    def _init_container(self):
        zbx_container = DataContainer(
            data_type = 'items' if self.options.probe_mode == 'update_items' else 'lld',
            zbx_file  = self.options.config_file,
            zbx_host  = self.options.zabbix_server,
            zbx_port  = int(self.options.zabbix_port),
            log_level = 4 if self.options.debug else None,
            dryrun    = self.options.dryrun,
            logger    = self.logger
        )
        return zbx_container

    def _get_metrics(self):
        # mandatory method
        raise NotImplementedError('method not implemented')

    def _get_discovery(self):
        # mandatory method
        raise NotImplementedError('method not implemented')

    def _init_probe(self):
        # non mandatory method
        pass

    def _parse_probe_args(self, parser):
        # non mandatory method
        return parser

    def run(self, options = None):
        # Parse command line options
        args = sys.argv[1:]
        if isinstance(options, list):
            args = options
        self.options = self._parse_args(args)
        self.options.probe_mode = 'update'
        if self.options.update is True and self.options.discovery is True:
            raise ValueError('Both --update-items & --discovery options detected. You must use only one at a time')
        elif self.options.discovery is True:
            self.options.probe_mode = 'discovery'

        # Datacontainer init
        zbx_container = self._init_container()
        # Get back hostname from DataContainer
        self.hostname = zbx_container.hostname

        # logger init
        # we need Zabbix configuration to know how to log
        self.logger = zbx_container.logger = self._setup_logging(zbx_container)

        # Step 1: read probe configuration
        #         initialize any needed object or connection
        try:
            self._init_probe()
        except:
            self.logger.error(
                'Step 1 - Read probe configuration failed'
            )
            self.logger.debug(traceback.format_exc())
            return 1

        # Step 2: get data
        try:
            data = {}
            if self.options.probe_mode == "update-items":
                data = self._get_metrics()
            elif self.options.probe_mode == "discovery":
                data = self._get_discovery()
        except Exception as e:
            self.logger.error(
                'Step 2 - Get Data failed [%s]' % str(e)
            )
            self.logger.debug(traceback.format_exc())
            return 2

        # Step 3: add data to container
        try:
            zbx_container.add(data)
        except Exception as e:
            self.logger.error(
                'Step 3 - Format & add Data failed [%s]' % str(e)
            )
            self.logger.debug(traceback.format_exc())
            return 3

        # Step 4: send data to Zabbix server
        try:
            zbx_container.send()
        except socket.error as e:
            self.logger.error(
                'Step 4 - Sent to Zabbix Server failed [%s]' % str(e)
            )
            self.logger.debug(traceback.format_exc())
            return 4
        except Exception as e:
            self.logger.error(
                'Step 4 - Unknown error [%s]' % str(e)
            )
            self.logger.debug(traceback.format_exc())
            return 4
        # Everything went fine. Let's return 0 and exit
        return 0
