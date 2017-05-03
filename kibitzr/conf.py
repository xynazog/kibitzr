import os
import re
import copy
import logging.config
import contextlib

import yaml


logger = logging.getLogger(__name__)


class ConfigurationError(RuntimeError):
    pass


class ReloadableSettings(object):
    _instance = None
    CONFIG_DIRS = (
        '',
        '~/.config/kibitzr/',
        '~/',
    )
    CONFIG_FILENAME = 'kibitzr.yml'
    CREDENTIALS_FILENAME = 'kibitzr-creds.yml'
    RE_PUNCTUATION = re.compile(r'\W+')
    UNNAMED_PATTERN = 'Unnamed check {0}'

    def __init__(self, config_dir):
        self.filename = os.path.join(config_dir, self.CONFIG_FILENAME)
        self.creds_filename = os.path.join(config_dir,
                                           self.CREDENTIALS_FILENAME)
        self.checks = None
        self.creds = {}
        self.parser = SettingsParser()
        self.reread()

    @classmethod
    def detect_config_dir(cls):
        candidates = [
            (directory, os.path.join(directory, cls.CONFIG_FILENAME))
            for directory in map(os.path.expanduser, cls.CONFIG_DIRS)
        ]
        for directory, file_path in candidates:
            if os.path.exists(file_path):
                return directory
        raise ConfigurationError(
            "kibitzr.yml not found in following locations: %s"
            % ", ".join([x[1] for x in candidates])
        )

    @classmethod
    def instance(cls):
        if cls._instance is None:
            config_dir = cls.detect_config_dir()
            cls._instance = cls(config_dir)
        return cls._instance

    def reread(self):
        """
        Read configuration file and substitute references into checks conf
        """
        logger.debug("Loading settings from %s",
                     os.path.abspath(self.filename))
        conf = self.read_conf()
        changed = self.read_creds()
        checks = self.parser.parse_checks(conf)
        if self.checks != checks:
            self.checks = checks
            return True
        else:
            return changed

    def read_conf(self):
        """
        Read and parse configuration file
        """
        with self.open_conf() as fp:
            return yaml.load(fp)

    @contextlib.contextmanager
    def open_conf(self):
        with open(self.filename) as fp:
            yield fp

    def read_creds(self):
        """
        Read and parse credentials file.
        If something goes wrong, log exception and continue.
        """
        logger.debug("Loading credentials from %s",
                     os.path.abspath(self.creds_filename))
        creds = {}
        try:
            with self.open_creds() as fp:
                creds = yaml.load(fp)
        except IOError:
            logger.info("No credentials file found at %s",
                        os.path.abspath(self.creds_filename))
        except:
            logger.exception("Error loading credentials file")
        if creds != self.creds:
            self.creds = creds
            return True
        return False

    @contextlib.contextmanager
    def open_creds(self):
        with open(self.creds_filename) as fp:
            yield fp


def settings():
    """
    Returns singleton instance of settings
    """
    return ReloadableSettings.instance()


class SettingsParser(object):
    RE_PUNCTUATION = re.compile(r'\W+')
    UNNAMED_PATTERN = 'Unnamed check {0}'

    def parse_checks(self, conf):
        """
        Unpack configuration from human-friendly form
        to strict check definitions.
        """
        checks = conf.get('checks', conf.get('pages', []))
        checks = list(self.unpack_batches(checks))
        checks = list(self.unpack_templates(checks, conf.get('templates', {})))
        self.inject_missing_names(checks)
        self.inject_scenarios(checks, conf.get('scenarios', {}))
        self.inject_notifiers(checks, conf.get('notifiers', {}))
        return checks

    @staticmethod
    def inject_notifiers(checks, notifiers):
        for check in checks:
            if 'notify' in check:
                for notify in check['notify']:
                    if hasattr(notify, 'keys'):
                        notify_type = next(iter(notify.keys()))
                        notify_param = next(iter(notify.values()))
                        try:
                            notify[notify_type] = notifiers[notify_param]
                        except (TypeError, KeyError):
                            # notify_param is not a predefined notifier name
                            # Save it as is:
                            notify[notify_type] = notify_param

    @staticmethod
    def inject_scenarios(checks, scenarios):
        for check in checks:
            try:
                shared_scenario = scenarios[check['scenario']]
            except (KeyError, TypeError):
                pass
            else:
                check['scenario'] = shared_scenario

    def unpack_batches(self, checks):
        for check in checks:
            if 'batch' in check:
                base = copy.deepcopy(check)
                batch = base.pop('batch')
                url_pattern = base.pop('url-pattern')
                items = base.pop('items')
                for item in items:
                    yield dict(
                        copy.deepcopy(base),
                        name=batch.format(item),
                        url=url_pattern.format(item),
                    )
            else:
                yield check

    @classmethod
    def inject_missing_names(cls, checks):
        unnamed_check_counter = 1
        for check in checks:
            if not check.get('name'):
                if check.get('url'):
                    check['name'] = cls.url_to_name(check['url'])
                else:
                    check['name'] = cls.UNNAMED_PATTERN.format(unnamed_check_counter)
                    unnamed_check_counter += 1

    @classmethod
    def url_to_name(cls, url):
        return cls.RE_PUNCTUATION.sub('-', url)

    @staticmethod
    def unpack_templates(checks, templates):
        for check in checks:
            if 'template' in check:
                if check['template'] in templates:
                    templated_check = dict(
                        copy.deepcopy(templates[check['template']]),
                        **check
                    )
                    del templated_check['template']
                    yield templated_check
                else:
                    raise ConfigurationError(
                        "Template %r not found. Referenced in check %r"
                        % (check['template'], check['name'])
                    )
            else:
                yield check


logging.config.dictConfig({
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
        },
    },
    'handlers': {
        'default': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'standard',
        },
    },
    'loggers': {
        '': {
            'handlers': ['default'],
            'level': 'INFO',
            'propagate': True,
        },
        'sh': {
            'level': 'INFO',
        },
        'sh.command': {
            'level': 'WARNING',
        },
    }
})
