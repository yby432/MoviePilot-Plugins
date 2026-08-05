from app.plugins import PluginBase
from .doki8 import Doki8CheckIn

class Plugin(PluginBase):
    def init_plugin(self):
        Doki8CheckIn(self).register()
