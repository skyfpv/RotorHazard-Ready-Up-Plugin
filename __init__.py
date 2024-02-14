import logging
import RHUtils
import json
import requests
import Config
from RHUI import UIField, UIFieldType, UIFieldSelectOption
import struct
from time import monotonic
from Database import ProgramMethod
from copy import deepcopy
from eventmanager import Evt
from RHRace import RaceStatus

logger = logging.getLogger(__name__)

#VERSION
VERSION_MAJOR = 1
VERSION_MINOR = 0

#Animations
ANIM_SOLID = 0
ANIM_BLINK = 1
ANIM_BLINK_FAST = 2
ANIM_SPARKLE = 3
ANIM_SIN_SCROLL = 4

#UI panels
RUN_PANEL_NAME = "ReadyUpRunPanel"
SETTINGS_PANEL_NAME = "ReadyUpSettingsPanel"

#DB options
OPT_COURSE_CLEAR = "RUTrackOpen"
OPT_IDLE_ANIMATION = "RUIdleAnimation"
OPT_REQUIRE_COURSE_CLEAR = "RURequireCourseClose"
OPT_PRE_STAGE_TIME = "RUPreStageTime"
OPT_PILOT_READY = "RUPilotReady"

#default values
DEFAULT_TRACK_OPEN = "0"
DEFAULT_PRE_STAGE_TIME = 13
DEFAULT_IDLE_ANIMATION = "BlinkFast"
DEFAULT_IDLE_COLOR = "ffffff"
DEFAULTS = {
    OPT_COURSE_CLEAR: DEFAULT_TRACK_OPEN,
    OPT_IDLE_ANIMATION: DEFAULT_IDLE_ANIMATION
}

DEFAULT_PILOT_READY_STATE = {"ready":False}

#COLORS/ANIMATIONS
ANIMATION_PILOT_READY = ANIM_SIN_SCROLL
ANIMATION_PILOT_IDLE = ANIM_BLINK
ANIMATION_PILOT_WIN = ANIM_BLINK_FAST

COLOR_RACE_STAGING = "#00000"
ANIMATION_RACE_STAGING = ANIM_SOLID

COLOR_RACE_START = "#00ff00"
ANIMATION_RACE_START = ANIM_SOLID

COLOR_RACE_STOP = "#ff0000"
ANIMATION_RACE_STOP = ANIM_SOLID

COLOR_RACE_SCHEDULED = "#ffff00"
ANIMATION_RACE_SCHEDULED = ANIM_BLINK

COLOR_COURSE_CLOSED = "#ffff00"
ANIMATION_COURSE_CLOSED = ANIM_SOLID

COLOR_COURSE_OPEN = "#ffffff"
ANIMATION_COURSE_OPEN = ANIM_BLINK

def initialize(rhapi):
    RH = RUManager(rhapi)

    logging.info("initializing ready up plugin")
    
    rhapi.ui.register_panel(RUN_PANEL_NAME, 'Ready Up', 'run', order=0)
    rhapi.ui.register_panel(SETTINGS_PANEL_NAME, 'Ready Up', 'settings')

    logging.debug("panels registered")

    trackClear = UIField(name = OPT_COURSE_CLEAR, label = 'Track Clear', field_type = UIFieldType.CHECKBOX, value = DEFAULT_TRACK_OPEN)
    rhapi.fields.register_option(trackClear, RUN_PANEL_NAME)

    requireCourseClear = UIField(name = OPT_REQUIRE_COURSE_CLEAR, label = 'Require Track Clear', field_type = UIFieldType.CHECKBOX, value = DEFAULT_TRACK_OPEN)
    rhapi.fields.register_option(requireCourseClear, SETTINGS_PANEL_NAME)

    preStageTime = UIField(name = OPT_PRE_STAGE_TIME, label = 'Pre-Staging Countdown', field_type = UIFieldType.BASIC_INT, value = DEFAULT_PRE_STAGE_TIME)
    rhapi.fields.register_option(preStageTime, SETTINGS_PANEL_NAME)

    #ready states
    node1Ready = UIField(name = OPT_PILOT_READY+"1", label = 'Pilot 1 Ready', field_type = UIFieldType.CHECKBOX, value = False)
    rhapi.fields.register_option(node1Ready, RUN_PANEL_NAME)

    node2Ready = UIField(name = OPT_PILOT_READY+"2", label = 'Pilot 2 Ready', field_type = UIFieldType.CHECKBOX, value = False)
    rhapi.fields.register_option(node2Ready, RUN_PANEL_NAME)

    node3Ready = UIField(name = OPT_PILOT_READY+"3", label = 'Pilot 3 Ready', field_type = UIFieldType.CHECKBOX, value = False)
    rhapi.fields.register_option(node3Ready, RUN_PANEL_NAME)

    node4Ready = UIField(name = OPT_PILOT_READY+"4", label = 'Pilot 4 Ready', field_type = UIFieldType.CHECKBOX, value = False)
    rhapi.fields.register_option(node4Ready, RUN_PANEL_NAME)

    node5Ready = UIField(name = OPT_PILOT_READY+"5", label = 'Pilot 5 Ready', field_type = UIFieldType.CHECKBOX, value = False)
    rhapi.fields.register_option(node5Ready, RUN_PANEL_NAME)

    node6Ready = UIField(name = OPT_PILOT_READY+"6", label = 'Pilot 6 Ready', field_type = UIFieldType.CHECKBOX, value = False)
    rhapi.fields.register_option(node6Ready, RUN_PANEL_NAME)

    node7Ready = UIField(name = OPT_PILOT_READY+"7", label = 'Pilot 7 Ready', field_type = UIFieldType.CHECKBOX, value = False)
    rhapi.fields.register_option(node7Ready, RUN_PANEL_NAME)

    node8Ready = UIField(name = OPT_PILOT_READY+"8", label = 'Pilot 8 Ready', field_type = UIFieldType.CHECKBOX, value = False)
    rhapi.fields.register_option(node8Ready, RUN_PANEL_NAME)

    logging.debug("registered options")
    
    logging.debug("ready up plugin initialized")

class RUManager():
    def __init__(self, rhapi):
        self.rhapi = rhapi
        
        #websocket listeners
        self.rhapi.ui.socket_listen("ready_up_toggle", self.handleReadyToggle)
        self.rhapi.ui.socket_listen("ready_up_get_state", self.handleJoin)
        self.rhapi.ui.socket_listen("ready_up_version", self.handleVersionRequest)

        #event handlers
        rhapi.events.on(Evt.OPTION_SET, self.handleOptionSet)
        rhapi.events.on(Evt.HEAT_SET, self.handleHeatSet)
        rhapi.events.on(Evt.RACE_STAGE, self.handleRaceStage)
        rhapi.events.on(Evt.RACE_START, self.handleRaceStart)
        rhapi.events.on(Evt.RACE_STOP, self.handleRaceStop)
        rhapi.events.on(Evt.RACE_FIRST_PASS, self.handleFirstPass)
        rhapi.events.on(Evt.RACE_WIN, self.handleRaceWin)
        rhapi.events.on(Evt.RACE_FINISH, self.handleRaceFinish)
        rhapi.events.on(Evt.LAPS_SAVE, self.handleSave)
        rhapi.events.on(Evt.LAPS_DISCARD, self.handleDiscard)
        rhapi.events.on(Evt.RACE_SCHEDULE, self.handleRaceScheduled)

        #main game state that will be distributed to all players as well as updated by them
        self.pilotReadyState = []
        for i in range(0,9):
            self.pilotReadyState.append(deepcopy(DEFAULT_PILOT_READY_STATE))
            if(i!=0):
                self.setOption(OPT_PILOT_READY+str(i), 0)

        #set default option values
        self.setOption(OPT_COURSE_CLEAR, DEFAULT_TRACK_OPEN)
        self.setOption(OPT_REQUIRE_COURSE_CLEAR, DEFAULT_TRACK_OPEN)
        self.setOption(OPT_PRE_STAGE_TIME, DEFAULT_PRE_STAGE_TIME)

        self.animations = [ANIM_SOLID, ANIM_SOLID, ANIM_SOLID, ANIM_SOLID, ANIM_SOLID, ANIM_SOLID, ANIM_SOLID, ANIM_SOLID, ANIM_SOLID]
        self.colors = ["#000000", "#000000", "#000000", "#000000", "#000000", "#000000", "#000000", "#000000", "#000000"]

    def getOption(self, option):
        if(self.rhapi.db.option(option)==None):
            default = DEFAULTS[option]
            self.setOption(option, default)
        return self.rhapi.db.option(option)

    def setOption(self, option, value, refreshUI=True):
        self.rhapi.db.option_set(option, value)
        if(refreshUI):
            self.rhapi.ui.broadcast_ui("run")

    def handleJoin(self, data):
        logging.debug("handle join")
        self.broadcastLEDInfo()

    def handleVersionRequest(self):
        logging.debug("handle version request")
        data = {"major":VERSION_MAJOR, "minor":VERSION_MINOR}
        logging.debug("-> "+str(data))
        self.rhapi.ui.socket_broadcast("ready_up_version", data)
        self.broadcastLEDInfo()

    def handleReadyToggle(self, data, forceValue=None):
        #{
        #    "ready_up_toggle":
        #    {
        #        "seat": 1,
        #    }
        #}
        seat = data["seat"]+1
        pilots = self.rhapi.race.pilots

        if(self.rhapi.race.status!=1):
            #if the race director button has been pressed
            if(seat==0):
                if(self.rhapi.race.status != RaceStatus.RACING):
                    self.pilotReadyState[seat]["ready"] = not self.pilotReadyState[seat]["ready"]
                    if(self.pilotReadyState[seat]["ready"]):
                        self.setOption(OPT_COURSE_CLEAR, "1")
                        uiMessage = "The course is clear for racing"
                        if(not self.allPilotsReady()):
                            uiMessage+=". Waiting for pilots to ready up"
                    else:
                        self.setOption(OPT_COURSE_CLEAR, "0")
                        uiMessage = "The course is no longer clear"

                    #self.setOption(COURSE_CLEAR, str(int(not self.pilotReadyState[seat]["ready"])))
                    
                    logging.debug("to "+str(int(self.pilotReadyState[seat]["ready"])))
                    #self.setOption(COURSE_CLEAR, "0")
                    self.rhapi.ui.message_notify(uiMessage)
                    self.rhapi.ui.message_speak(uiMessage)
            #if one of the pilot's buttons has been pressed
            else:
                pilotById = self.getPilotById(pilots[seat-1])
                if(pilotById != None):
                    #if a value is being forced
                    if(forceValue!=None):
                        logging.debug("force toggle to "+str(forceValue))
                        self.pilotReadyState[seat]["ready"] = forceValue
                        #update the option in the run page
                        logging.debug("changed option for pilot: "+OPT_PILOT_READY+str(seat)+"="+str(int(self.pilotReadyState[seat]["ready"])))
                        #self.setOption(PILOT_READY+str(seat), int(self.pilotReadyState[seat]["ready"]), refreshUI=False)
                    else:
                        #toggle the pilot's ready state
                        logging.debug("toggle from "+str(self.pilotReadyState[seat]["ready"])+" to "+str(not self.pilotReadyState[seat]["ready"]))
                        self.pilotReadyState[seat]["ready"] = not self.pilotReadyState[seat]["ready"]
                        
                        self.setOption(OPT_PILOT_READY+str(seat), int(self.pilotReadyState[seat]["ready"]), refreshUI=True)
                    
                    #create UI audio and text alerts
                    if(self.pilotReadyState[seat]["ready"]):
                        #self.pilotReadyState[seat]["ready"] = True
                        uiMessage = self.getPilotById(pilots[seat-1]).callsign+" is ready"
                        if(self.allPilotsReady()):
                            uiMessage = uiMessage+". All pilots ready"
                            #self.rhapi.ui.message_speak("All pilots are ready to race")
                    else:
                        #self.pilotReadyState[seat]["ready"] = False
                        if(self.rhapi.race.scheduled!=None):
                            self.rhapi.race.schedule(0, 0)
                            uiMessage = self.getPilotById(pilots[seat-1]).callsign+" has canceled the countdown"
                        else:
                            uiMessage = self.getPilotById(pilots[seat-1]).callsign+" is preparing"

                    logging.debug("pilot ready states: "+str(self.pilotReadyState))
                    self.updatePilotButtonLEDs(seat, self.getReadyStateAnimation(seat), self.getPilotColor(seat-1))

                    #display a UI message when players press their ready-up buttons
                    self.rhapi.ui.message_notify(uiMessage)
                    self.rhapi.ui.message_speak(uiMessage)
            self.handleReadyStateChange(forceCourseClear=(seat-1==-1))

        else:
            if(seat==0):
                self.rhapi.race.stop(doSave=False)
            else:
                uiMessage = "A challange has been raised by "+self.getPilotById(pilots[seat-1]).callsign
                self.rhapi.ui.message_alert(uiMessage)
                self.rhapi.ui.message_speak(uiMessage)

    def allPilotsReady(self):
        pilots = self.rhapi.race.pilots
        allPilotsReady = True
        
        #check if any pilot is not yet ready
        for i in range(1,len(pilots)+1):
            pilotId = pilots[i-1]
            #check if a pilot is occupying the seat
            if(pilotId!=0):
                #check if the pilot is not ready
                if(not self.pilotReadyState[i]["ready"]):
                    allPilotsReady = False
        return allPilotsReady

    def handleReadyStateChange(self, forceCourseClear=False):
        #if all pilots are ready
        if(self.allPilotsReady()==True):
            logging.debug("course clear: "+str(self.getOption(OPT_COURSE_CLEAR)))
            logging.debug("- required: "+str(self.getOption(OPT_REQUIRE_COURSE_CLEAR)))
            #if the course is clear or the race director doesn't require it to be clear (E.G. whoop races)
            if(int(self.getOption(OPT_COURSE_CLEAR))==1 or int(self.getOption(OPT_REQUIRE_COURSE_CLEAR))==0):
                self.scheduleRace(self.getOption(OPT_PRE_STAGE_TIME))
            else:
                self.rhapi.ui.message_notify("Please clear the track")
                self.rhapi.ui.message_speak("Please clear the track")
        if(int(self.getOption(OPT_COURSE_CLEAR))==1):
            self.updateRaceDirectorButtonLEDs(ANIMATION_COURSE_CLOSED, COLOR_COURSE_CLOSED)
        else:
            self.updateRaceDirectorButtonLEDs(ANIMATION_COURSE_OPEN, COLOR_COURSE_OPEN)
        self.broadcastLEDInfo()

    def updatePilotButtonLEDs(self, seat, animation, color):
        self.animations[seat] = animation
        self.colors[seat] = color
        #self.broadcastLEDInfo()

    def updateAllPilotButtonLEDs(self, animation, color):
        for seat in range(1,9):
            self.animations[seat] = animation
            self.colors[seat] = color
        #self.broadcastLEDInfo()

    def updateRaceDirectorButtonLEDs(self, animation, color):
        self.animations[0] = animation
        self.colors[0] = color
        #self.broadcastLEDInfo()

    def broadcastLEDInfo(self, raceWinnerColor=None):
        logging.debug("broadcastLEDInfo()")
        data = {"patterns":self.animations, "colors":self.colors}
        logging.debug("-> "+str(data))
        self.rhapi.ui.socket_broadcast("ready_up_leds", data)
    
    def resetPilotReadyStates(self):
        for i in range(0,8):
            self.pilotReadyState[i] = deepcopy(DEFAULT_PILOT_READY_STATE)
            refresh = i==8
            #don't set pilot ready option for the race director slot
            if(i!=0):
                self.setOption(OPT_PILOT_READY+str(i), 0, refreshUI=refresh)

    def scheduleRace(self, delaySeconds=6):
        logging.debug("schedule race in "+str(delaySeconds)+" seconds")
        #if(self.rhapi.race.scheduled==None):
        self.rhapi.race.schedule(delaySeconds)

    def getPilotById(self, pilotId):
        return self.rhapi.db.pilot_by_id(pilotId)
    
    def getPilotColor(self, seatIndex):
        pilotColor = "#000000"
        pilot = self.rhapi.db.pilot_by_id(self.rhapi.race.pilots[seatIndex])
        if(pilot!=None):
            pilotColor = pilot.color
        return pilotColor

    #TO-DO: figure out what format of color is being returned and convert it to hex
    # def getPilotColor(self, seatIndex):
    #     pilotColor = "#000000"
    #     try:
    #         pilotColor = self.rhapi.race.seat_colors[seatIndex]
    #     except:
    #         pass
    #     logging.info("getPilotColor: "+str(pilotColor))
    #     return pilotColor


    #broadcasts steam IDs of pilots in the current heat indexed by seat
    def broadcastPilotInfo(self):
        logging.debug("broadcastPilotInfo")
        info = {"info":[]}
        self.rhapi.ui.socket_broadcast("fs_player_info", info)

    def handleOptionSet(self, data):
        logging.debug("handleOptionSet()")
        logging.debug(data)
        if(data["option"] == OPT_COURSE_CLEAR):
            self.pilotReadyState[0] = data["value"]
            self.handleReadyStateChange()
        if(OPT_PILOT_READY in data["option"]):
            logging.debug(self.pilotReadyState)
            seat = int(data["option"][-1])-1
            if(self.pilotReadyState[seat]!=data["value"]):
                self.handleReadyToggle({"seat":seat},forceValue=data["value"])

    def handleHeatSet(self, data):
        logging.debug("Event: handleHeatSet - "+str(data))
        #self.resetPilotReadyStates()
        for i in range(1,9):
            animation = self.getReadyStateAnimation(i)
            self.updatePilotButtonLEDs(i, animation, self.getPilotColor(i-1))
        self.broadcastLEDInfo()

    def handleRaceScheduled(self, data):
        logging.debug("Event: handleRaceScheduled - "+str(data))
        self.updateAllPilotButtonLEDs(ANIMATION_RACE_SCHEDULED, COLOR_RACE_SCHEDULED)
        self.updateRaceDirectorButtonLEDs(ANIMATION_RACE_SCHEDULED, COLOR_RACE_SCHEDULED)
        self.broadcastLEDInfo()

    def handleRaceStage(self, data):
        logging.debug("Event: handleRaceStage - "+str(data))
        self.resetPilotReadyStates()
        self.setOption(OPT_COURSE_CLEAR, "0")
        self.updateAllPilotButtonLEDs(ANIMATION_RACE_STAGING, COLOR_RACE_STAGING)
        self.updateRaceDirectorButtonLEDs(ANIMATION_RACE_STAGING, COLOR_RACE_STAGING)
        self.broadcastLEDInfo()

    def handleRaceStart(self, data):
        logging.debug("Event: handleRaceStart - "+str(data))
        self.updateAllPilotButtonLEDs(ANIMATION_RACE_START, COLOR_RACE_START)
        self.updateRaceDirectorButtonLEDs(ANIMATION_RACE_START, COLOR_RACE_START)
        self.broadcastLEDInfo()

    def handleRaceStop(self, data):
        logging.debug("Event: handleRaceStop - "+str(data))
        self.updateAllPilotButtonLEDs(ANIMATION_RACE_STOP, COLOR_RACE_STOP)
        self.updateRaceDirectorButtonLEDs(ANIMATION_RACE_STOP, COLOR_RACE_STOP)
        self.broadcastLEDInfo()
        
    def handleRaceWin(self, data):
        logging.debug("Event: handleRaceWin - "+str(data))
        winnerSeatColor = self.getPilotColor(data["win_status"]["data"]["node"])
        logging.debug("Event: winner color - "+str(winnerSeatColor))
        self.updateAllPilotButtonLEDs(ANIMATION_PILOT_WIN, winnerSeatColor)
        self.updateRaceDirectorButtonLEDs(ANIMATION_PILOT_WIN, winnerSeatColor)
        self.broadcastLEDInfo()

    def handleFirstPass(self, data):
        logging.debug("Event: handleFirstPass - "+str(data))
        {'node_index': 0, '_eventName': 'raceFirstPass'}
        
        self.updatePilotButtonLEDs(data["node_index"]+1, ANIMATION_PILOT_READY, self.getPilotColor(data["node_index"]))
        self.broadcastLEDInfo()

    def handleRaceFinish(self, data):
        logging.debug("Event: handleRaceFinish - "+str(data))
        # animation = ANIM_SIN_SCROLL
        # for i in range(1,9):
        #     self.updatePilotButtonLEDs(i, animation, self.getSeatColor(i-1))
        self.updateRaceDirectorButtonLEDs(ANIMATION_RACE_STOP, COLOR_RACE_STOP)
        self.broadcastLEDInfo()

    def handleSave(self, data):
        logging.debug("Event: handleSave - "+str(data))
        for i in range(1,9):
            animation = self.getReadyStateAnimation(i)
            self.updatePilotButtonLEDs(i, animation, self.getPilotColor(i-1))
        self.updateRaceDirectorButtonLEDs(ANIMATION_COURSE_OPEN, COLOR_COURSE_OPEN)
        self.broadcastLEDInfo()

    def handleDiscard(self, data):
        logging.debug("Event: handleDiscard - "+str(data))
        for i in range(1,9):
            animation = self.getReadyStateAnimation(i)
            self.updatePilotButtonLEDs(i, animation, self.getPilotColor(i-1))
        self.updateRaceDirectorButtonLEDs(ANIMATION_COURSE_OPEN, COLOR_COURSE_OPEN)
        self.broadcastLEDInfo()

    def getReadyStateAnimation(self, buttonIndex):
        if(self.pilotReadyState[buttonIndex]["ready"]):
            return ANIMATION_PILOT_READY
        else:
            return ANIMATION_PILOT_IDLE