import datetime
import time
import validators

from mycroft.skills.core import (MycroftSkill,
                                 intent_handler, intent_file_handler)
from mycroft.messagebus.message import Message
from ovos_skills_manager.osm import OVOSSkillsManager
from ovos_skills_manager.appstores.pling import get_pling_skills
from ovos_skills_manager.appstores.ovos import get_ovos_skills
from json_database import JsonStorage


class AppStoreModel:
    app_store_name: str
    model: list
    db_loc: str
    storage: JsonStorage

    def __init__(self, name: str, model: list, db_loc: str):
        self.app_store_name = name
        self.model = model
        self.db_loc = db_loc
        self.storage = JsonStorage(db_loc)

class OSMInstaller(MycroftSkill):

    def __init__(self):
        super(OSMInstaller, self).__init__(name="OSMInstaller")
        self.osm_manager = OVOSSkillsManager()
        self.enabled_appstores = self.osm_manager.get_active_appstores()
        self.appstores = {}

        for appstore_name, appstore in self.enabled_appstores.items():
            self.appstores[appstore_name] = AppStoreModel(
                name=appstore.appstore_id,
                model=[],
                db_loc=appstore.db.path
            )
        self.search_skills_model = []

    def initialize(self):
        self.add_event("OSMInstaller.openvoiceos.home",
                       self.handle_display_home)
        self.add_event("osm.sync.finish",
                       self.update_display_model)
        self.add_event("osm.install.finish", self.display_installer_success)
        self.add_event("osm.install.error", self.display_installer_failure)
        self.gui.register_handler("OSMInstaller.openvoiceos.install",
                                  self.handle_install)

        # Build The Initial Display Model Without Sync
        # Make Sure Models Are Built Early To Avoid Display Call Delay
        self.update_display_model()

        # First Sync
        self.log.info(self.enabled_appstores.keys())
        self.osm_manager.sync_appstores()
        # Start A Scheduled Event for Syncing OSM data
        now = datetime.datetime.now()
        callback_time = datetime.datetime(
            now.year, now.month, now.day, now.hour, now.minute
        ) + datetime.timedelta(seconds=60)
        self.schedule_repeating_event(self.sync_osm_model, callback_time, 9000)

    @intent_file_handler("show-osm.intent")
    def handle_display_home(self):
        self.gui.show_page("AppstoreHome.qml", override_idle=True)

    @intent_file_handler("search-osm.intent")
    def handle_search_osm_intent(self, message):
        utterance = message.data.get("description", "")
        if utterance is not None:
            results = self.osm_manager.search_skills(utterance)
            for m_skill in results:
                if m_skill.skill_name is not None:
                    self.search_skills_model.append({
                        "title": m_skill.skill_name,
                        "description": m_skill.skill_description,
                        "logo": m_skill.json.get("logo"),
                        "author": m_skill.skill_author,
                        "category": m_skill.skill_category,
                        "url": m_skill.url
                        })

            self.gui["appstore_pling_model"] = self.search_skills_model

    def build_skills_model(self, appstore):
        self.log.info(f"Building model for {appstore}")

        if appstore in self.enabled_appstores:
            if appstore == "ovos":
                self.log.info("Selected OVOS Appstore")
                _ = self.build_ovos_skills_model()
                self.appstores["ovos"].storage.store()
            elif appstore == "pling":
                self.log.info("Selected Pling Appstore")
                if "model" not in self.appstores["pling"].storage:
                    _  = self.build_pling_skills_model()
                    self.appstores["pling"].storage.store()
        else:
            self.log.info(f"requested appstore '{appstore}' disabled or invalid")

    # Build Custom Display Model For OVOS Skill Store
    def build_ovos_skills_model(self):
        self.appstores["ovos"].model.clear()
        for m_skill in self.enabled_appstores["ovos"]:
            if m_skill.skill_name is not None:
                self.log.info(validators.url(m_skill.skill_icon))
                if validators.url(m_skill.skill_icon):
                    skill_icon = m_skill.skill_icon
                else:
                    skill_icon = "https://iconarchive.com/download/i103156\
                    /blackvariant/button-ui-requests-9/Parcel.ico"
                self.appstores["ovos"].model.append({
                    "title": m_skill.skill_name,
                    "description": m_skill.skill_description,
                    "logo": skill_icon,
                    "author": m_skill.skill_author,
                    "category": m_skill.skill_category,
                    "url": m_skill.url
                    })

        return self.appstores["ovos"]

    # Build Custom Display Model For Pling Skill Store
    def build_pling_skills_model(self):
        self.appstores["pling"].model.clear()
        for m_skill in self.enabled_appstores["pling"]:
            if m_skill.skill_name is not None:
                self.appstores["pling"].model.append({
                    "title": m_skill.skill_name,
                    "description": m_skill.skill_description,
                    "logo": m_skill.json.get("logo"),
                    "author": m_skill.skill_author,
                    "category": m_skill.skill_category,
                    "url": m_skill.url
                    })

        return self.appstores["pling"].model

    def handle_install(self, message):
        skill_url = message.data.get("url")
        self.gui["installer_status"] = 1 # Running
        self.log.info("Got request to install: " + skill_url)
        self.osm_manager.install_skill_from_url(skill_url)

    def sync_osm_model(self):
        self.osm_manager.sync_appstores()

    def update_display_model(self):
        try:
            self.build_skills_model("ovos")
        except KeyError:
            pass
        try:
            self.build_skills_model("pling")
        except KeyError:
            pass
        self.update_display_data()

    def update_display_data(self):
        self.gui["installer_status"] = 0 # Idle / Unknown
        try:
            self.gui["appstore_ovos_model"] = self.appstores["ovos"].model
        except KeyError:
            pass
        try:
            self.gui["appstore_pling_model"] = self.appstores["pling"].model
        except KeyError:
            pass

    def display_installer_success(self):
        self.log.info("Installer Successful")
        self.gui["installer_status"] = 2 # Success
        time.sleep(2)
        self.update_display_model()

    def display_installer_failure(self):
        self.log.info("Installer Failed")
        self.gui["installer_status"] = 3 # Fail
        time.sleep(2)
        self.update_display_model()

def create_skill():
    return OSMInstaller()
