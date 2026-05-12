"""配置加载模块"""
import logging
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)


class Config:
    """配置管理类"""

    _instance: Optional['Config'] = None
    _config: dict = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def load(self, config_path: Optional[str] = None) -> dict:
        """加载配置文件"""
        if config_path is None:
            config_path = Path(__file__).parent.parent / "config.yaml"

        with open(config_path, 'r', encoding='utf-8') as f:
            self._config = yaml.safe_load(f)

        self._validate()
        logger.info("配置文件加载成功")
        return self._config

    def _validate(self):
        """验证必要配置项"""
        required_sections = ['account', 'purchase', 'browser', 'debug']
        for section in required_sections:
            if section not in self._config:
                raise ValueError(f"配置缺少必要section: {section}")

        if not self._config['account'].get('phone'):
            raise ValueError("配置缺少 account.phone")

        if not self._config['account'].get('password'):
            logger.warning("account.password 为空，将使用验证码登录")

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置项，支持点号分隔如 'purchase.hour'"""
        keys = key.split('.')
        value = self._config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
            if value is None:
                return default
        return value

    @property
    def account(self) -> dict:
        return self._config.get('account', {})

    @property
    def purchase(self) -> dict:
        return self._config.get('purchase', {})

    @property
    def browser(self) -> dict:
        return self._config.get('browser', {})

    @property
    def debug(self) -> dict:
        return self._config.get('debug', {})


# 全局配置实例
config = Config()
