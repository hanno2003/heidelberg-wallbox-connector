#!/usr/bin/env python3
import minimalmodbus
import serial
import time
import datetime
import paho.mqtt.client as mqtt
import logging
from logging.handlers import TimedRotatingFileHandler
import gzip
import os
from configparser import ConfigParser

from heidelberg import wallbox

######################################
#
#   V 1.0: 03.02.2021:  Initail Release
#   V 1.1: 04.02.2021   Added subscribe to max Current via MQTT
#   V 1.2: 06.02.2021   Added discrete Config File
#

#Read config.ini file
config_object = ConfigParser()
config_object.read("config.ini")

general_Config = config_object["general"]
mqtt_config = config_object["MQTT Broker Config"]
Modbus_Config = config_object["Modbus Config"]

######################################
#   MQTT Config
######################################

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

######################################
#   Modbus Config
######################################

wb = wallbox(Modbus_Config["usb_device"], 1)
maxCurrent = 0  # Initial maxCurrent, will be replaced by value from mqtt
#wb._reInitialize()
#wb.set_current_preset(maxCurrent)

######################################


######################################
#   Logging
######################################

try:
    os.makedirs(general_Config["log_path"])
    print("Logdir " + general_Config["log_path"] + " created" )
      
except FileExistsError:
    pass
    

class GZipRotator:
    def __call__(self, source, dest):
        os.rename(source, dest)
        f_in = open(dest, 'rb')
        f_out = gzip.open("%s.gz" % dest, 'wb')
        f_out.writelines(f_in)
        f_out.close()
        f_in.close()
        os.remove(dest)

#get the root logger
rootlogger = logging.getLogger()
#set overall level to debug, default is warning for root logger
rootlogger.setLevel(logging.DEBUG)

#setup logging to file, rotating at midnight
filelog = logging.handlers.TimedRotatingFileHandler(general_Config["log_path"]+general_Config["log_filename"], when='midnight', interval=1)
filelog.setLevel(logging.INFO)
fileformatter = logging.Formatter('%(asctime)s %(levelname)-8s %(message)s')
filelog.setFormatter(fileformatter)
filelog.rotator = GZipRotator()
rootlogger.addHandler(filelog)

consoleHandler = logging.StreamHandler()
consoleHandler.setFormatter(fileformatter)
rootlogger.addHandler(consoleHandler)

#get a logger for my script
logger = logging.getLogger(__name__)

######################################
#   Homie Initialisierung
######################################

def get_time():
    now = (datetime.datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    return now    

def on_connect(client, userdata, flags, rc, properties):
    logger.debug("Connected with result code " + str(rc))
    advertize_device()
    
    # Subscribing in on_connect() means that if we lose the connection and
    # reconnect then subscriptions will be renewed.
    client.subscribe("homie/Heidelberg-Wallbox/#")

            
def advertize_device():
    # Initialisierung nach Homie Standard
    client.publish("homie/Heidelberg-Wallbox/$homie", "3.0.0", 1, True)
    client.publish("homie/Heidelberg-Wallbox/$name", "Heidelberg Energy Control", 1, True)
    client.publish("homie/Heidelberg-Wallbox/$state", "ready", 1, True)
    client.publish("homie/Heidelberg-Wallbox/$extensions", "", 1, True)
    client.publish("homie/Heidelberg-Wallbox/$nodes", "wallbox", 1, True)

    # Stromzähler gesamt    
    client.publish("homie/Heidelberg-Wallbox/wallbox/$name", "Werte Wallbox", 1, True)
    client.publish("homie/Heidelberg-Wallbox/wallbox/$properties", "akt_verbrauch,zaehlerstand,max_current", 1, True)
    
    client.publish("homie/Heidelberg-Wallbox/wallbox/akt_verbrauch/$name", "Aktueller Verbrauch", 1, True)
    client.publish("homie/Heidelberg-Wallbox/wallbox/akt_verbrauch/$unit", "Watt", 1, True)
    client.publish("homie/Heidelberg-Wallbox/wallbox/akt_verbrauch/$datatype", "integer", 1, True)
    
    client.publish("homie/Heidelberg-Wallbox/wallbox/zaehlerstand/$name", "Zählerstand", 1, True)
    client.publish("homie/Heidelberg-Wallbox/wallbox/zaehlerstand/$unit", "kWh", 1, True)
    client.publish("homie/Heidelberg-Wallbox/wallbox/zaehlerstand/$datatype", "float", 1, True)

    client.publish("homie/Heidelberg-Wallbox/wallbox/max_current/$name", "Max Ladeleistung", 1, True)
    client.publish("homie/Heidelberg-Wallbox/wallbox/max_current/$unit", "A", 1, True)
    client.publish("homie/Heidelberg-Wallbox/wallbox/max_current/$datatype", "integer", 1, True)
    client.publish("homie/Heidelberg-Wallbox/wallbox/max_current/$settable", "true", 1, True)
    
def on_message_maxCurrent(client, userdata, message):
    global maxCurrent
    maxCurrent = int(message.payload.decode("utf-8"))
    logger.info("New Max Current received:" + str(maxCurrent))  
            
    
client.message_callback_add("homie/Heidelberg-Wallbox/wallbox/max_current/set", on_message_maxCurrent)
client.on_connect = on_connect
try:
    client.connect(mqtt_config["broker_IP"], 
                   mqtt_config["broker_port"], 
                   60)
except:
    logger.info("Could not connect to MQTT Broker")  
client.loop_start()

######################################
#   Main Loop
######################################

def loop():
    while True:
        
        ######################################
        #    Deactivate Watchdog Timeout
        ######################################
        #try:
        #    wb.set_watchdog_timeout(0)

        #    wallbox.write_register(registeraddress=257, value=0, numberOfDecimals=0, functioncode=6, signed=False)
        #    wb.
        #except:
        #     logger.info("Could not write to Modbus to deactivate Watchdog timeout")
        
        logger.info("Watchdog Time out is " + str(wb.get_watchdog_timeout()) + " ms")

        ######################################
        #   Send max Current to Wallbox
        ######################################
        try:
            logger.info("Set max current to: " + str(maxCurrent) + " A")  
            wb.set_current_preset(maxCurrent)            
            client.publish("homie/Heidelberg-Wallbox/wallbox/max_current", maxCurrent, 0, True)

        except:
            logger.info("Something wrong while sending max Current to MQTT")  
        
        
        ######################################
        #   Read Values from Wallbox
        ######################################
        try:
            #Total Energy
            WallboxZaehlerstand = wb.get_total_energy() 
    
            # Current Power    
            Adr_14 = wb.get_power()
        
            logger.info("WALLBOX,Zähler=Wallbox Zählerstand=" + str(WallboxZaehlerstand) + ",aktueller_verbrauch=" + str(Adr_14))  

            
            ######################################
            #   Homie publish
            ######################################
        
            client.publish("homie/Heidelberg-Wallbox/wallbox/akt_verbrauch", Adr_14, 0, False)
            client.publish("homie/Heidelberg-Wallbox/wallbox/zaehlerstand", WallboxZaehlerstand, 0, True)

            client.publish("homie/Heidelberg-Wallbox/$state", wb.get_state(), 1, True)

            state = wb.get_state()

            logging.info("Wallbox State: " + str(state))
            if state == 2:
                logging.info("No Vehicle Connected, Wallbox doesn't allow charging")
            elif state == 3:
                logging.info("No Vehicle Connected, Wallbox allows charging")
            elif state == 4:
                logging.info("Vehicle Connected without Charging request, Wallbox doesn't allow charging")
            elif state == 5:
                logging.info("Vehicle Connected without Charging request, Wallbox allows charging")
            elif state == 6:
                logging.info("Vehicle Connected with Charging request, Wallbox doesn't allow charging")
            elif state == 7:
                logging.info("Vehicle Connected with Charging request, Wallbox allows charging")
            elif state == 9:
                logging.info("Error state")

        except IOError:
            logger.info("Reading Wallbox failed, probably standby")  
        except:
            raise

        time.sleep(10)

try:
    logger.info("------------ Wallbox Controller started ------------")
    time.sleep(5)   #Wait 5 Seconds for MQTT to Connect and Pull Messages
    loop()
except:
    logger.info("------------ Client exited ------------")
    client.publish("homie/Heidelberg-Wallbox/$state", "disconnected", 1, True)
    client.disconnect()
    client.loop_stop()
    wb.set_current_preset(0) 
finally:
    logger.info("------------ Stopping client ------------")
    client.publish("homie/Heidelberg-Wallbox/$state", "disconnected", 1, True)
    client.disconnect()
    client.loop_stop()
    wb.set_current_preset(0)
