### Valentino Mariotto 2020 ###


## utili?
# import RPi.GPIO as GPIO 
# GPIO.cleanup()

# lcd.close()

import re       # regex lib
import logging
import sys
import signal
from RPLCD      import i2c
from mpd        import MPDClient
from time       import sleep
from threading  import Thread, Condition, Event


## logging setup
logging.basicConfig(filename='/home/pi/logs/mopidyLCDdrive.py.log', level=logging.WARNING)


## speed settings
scrolling_delay = 0.3 # seconds
data_refresh_rate = 0.5 # seconds
i2c_cmd_delay = 0.1 # seconds


## Initialise the LCD
lcdmode = 'i2c'             #
cols = 16                   # 16 or 20
rows = 2                    # 1, 2 or 4
charmap = 'A00'             # A00 or A02 or ST0B
dotsize = 8                 # 8 or 10 pixel char height
i2c_expander = 'PCF8574'    # “PCF8574”, “MCP23008”, “MCP23017”.
#expander_params={‘gpio_bank’:‘A’}  # only for MCP23017 - A or B
address = 0x27              # Find using: i2cdetect -y 1
port = 1                    # 0 on an older Raspberry Pi


try:
        lcd = i2c.CharLCD(i2c_expander, address,
                          port=port, charmap=charmap,
                          cols=cols, rows=rows,
                          dotsize=dotsize,
                          backlight_enabled=True,
                          auto_linebreaks=True) # False non funziona, true forse causa sovrapposizioni
except IOError:
    logging.critical("Nessun display LCD")
    ####print("ERRORE: nessun display LCD")
    raise SystemExit

lcd.cursor_mode = 'hide'
logging.info("Display OK")
####print("display OK")




## Connect to mpd client
MPD_server = "localhost" 
MPD_port = 6600
mpdc = MPDClient()
# diamo tempo a mopidy di partire, ma se ci mette troppo generiamo un errore
mpdc.timeout = 30 #seconds




## definisco:

newInfo = [
    "",
    ""
]
oldInfo = [
    "",
    ""
]


class Coda:
    def __init__(self):
        self.list = []

    # add to list method for producer
    def put(self, item):
        self.list.append(item)
    
    def size(self):
        s = len(self.list)
        return s

    # remove item from list method for consumer
    def get(self):
        item = self.list.pop(0)
#        print("Uso: ", item)
        return item



class GracefulKiller:
  kill_now = False
  def __init__(self):
    signal.signal(signal.SIGINT, self.exit_gracefully)
    signal.signal(signal.SIGTERM, self.exit_gracefully)

  def exit_gracefully(self,signum, frame):
    self.kill_now = True
    

    
## ottengo nuove informazioni
def GetInfo():
    
    text = [
        "",
        ""
    ]
    procpath = '/proc/asound/card0/pcm0p/sub0/hw_params'
    
    while True:
        try:
            card0now = open(procpath,'r')

        except IOError:
            # scheda audio non rilevata
            text[0] = "no audio output"
            
        else:
            hwinfos = card0now.readlines()
            if len(hwinfos)<=1:
                # scheda audio spenta!
                freq = 0
                bitStr = "--"
            else:
                # scheda in uso
                freqStr = (hwinfos[4])[6:12]
                freq = int(freqStr)/1000
                # print(freq)
                # logging.debug(freq)
                bits = re.compile("(16|24|32)")
                matchR = bits.search(hwinfos[1])
                if matchR:
                        bitStr = matchR.group(1)
                else:
                        bitStr = "--"
                # print(bitStr)
                # logging.debug(bitStr)

            text[0] = "{0:.1f}kHz {1}bit".format(freq,bitStr)



        # qui ottieniamo dati da mpd
        dataPoints = ['artist', 'title', 'name', 'bitrate'] #'album']
        
        try:
            mpdc.connect(MPD_server, MPD_port)
            
        # except ConnectionRefusedError:
            # text[1] = 'MPD unreachable'
            
        except Exception as err:
      
            if str(err) == 'Already connected':
                # normale, siamo già collegati
                pass
            else:
                # raccogliamo tutti gli altri errori
                # print(err)
                logging.error(err)
                text[1] = type(err).__name__
                return text
        # non posso usare else perché anche se ignoro l'eccezione non viene eseguito
        # non posso usare finally perché ci sono le altre eccezioni
        # mpdclient fa cagare
        
        try:
            mpdStat = mpdc.status()
        
        except Exception as err:
            # raccogliamo tutti gli altri errori
            # print(err)
            logging.error(err)
            text[1] = type(err).__name__
            return text
            
        else:
            if mpdStat['state'] != "play":
                text[1] = mpdStat['state']
            else:
                songInfo = mpdc.currentsong()
                for p in dataPoints:
                    if p in songInfo:
                        text[1] += songInfo[p]+" - "
                text[1] = text[1][0:-3] #substring: rimuovo il trattino in eccesso
            
            return text




## confronto 2 liste
def same_lists(list_a, list_b):
    if len(list_a) != len(list_b):
        return False
    if set(list_a) == set(list_b):
        return True
    else:
        return False



## faccio scorrere una riga di testo sul display
def Scroller(riga, scroll, q, blck_q):
    
    # print("SCROLLER RIGA "+str(riga)+" ATTIVO")
    # logging.debug("SCROLLER RIGA "+str(riga)+" ATTIVO")
    
    global cols, scrolling_delay
    text = ""
    framebuffer = ""
    padding = ' ' * cols
        
    while True: # così ricomincia da capo se per caso il loop sottostante si esaurisce mentre ok_scroll == false
        while scroll.wait(): # così avviene release! aspettiamo via libera
                
            blck_q.acquire()
            
            try:
                text = q.get()
                
            except:
####                print("<<    >>")
                # logging.debug("<<    >>")
                pass #ignora la coda vuota e continua a usare text dall'iterazione precedente
            
            finally:
                blck_q.release()
                
                s = padding + text + padding
                for i in range(len(s) -cols +1):
                
                    if not scroll.is_set(): # senza di questo non funziona??? bug???
                        break
                    if q.size()>0:
                        break # quando cambiano le info da mostrare non aspettiamo che questo loop finisca
                    framebuffer = s[i:i+cols]
####                    print(framebuffer)
                    # logging.debug(framebuffer)
                    lcd.cursor_pos = (riga,0)
                    lcd.write_string(framebuffer.ljust(cols)[:cols]) # -1 auto_linebreaks=False
                    sleep(scrolling_delay)





## gestisco il display
def UpdateDisplay(newInfo, q, blck_q, s):
    
    for r in range(len(newInfo)):
        s[r].clear() # impedisco scrolling
    
    sleep(i2c_cmd_delay *2) # aspetto che la coda di comandi per il display si svuoti
    lcd.clear() # pulisco il display
####    print("#" * cols)
    # logging.debug("#" * cols)
    

    for r in range(len(newInfo)):

        sleep(i2c_cmd_delay) # aspetta a dare i comandi tra una riga e l'altra

        #se il testo è troppo lungo faccio scrolling verso sinistra
        if len(newInfo[r]) > cols: # >= causa errori RPLCD
            
            # aggiungo info in coda
            blck_q.acquire() # blocco la coda    
            try:
                q.put(newInfo[r]) # aggiungo alla coda, che è un oggetto di classe audioInfo
                blck_q.notify() # avverto che disponibile
            except:
                break
            else:
                s[r].set() # consento lo scrolling
            finally:
                blck_q.release() # sblocco la coda


        #sennò evito il refresh continuo
        else:
            lcd.cursor_pos = (r,0)
            clear = ' ' * (cols -len(newInfo[r])) # -1 se auto_linebreaks=False
            lcd.write_string(newInfo[r] + clear)
####            print(newInfo[r])
            # logging.debug(newInfo[r])




## INIT LOOP
if __name__ == '__main__':

    killer = GracefulKiller()
    
    ## threading setup
    q = Coda()
    blck_q = Condition() # lock: per gestire la coda
    s = [] # evento: scrolling ON/OFF
    ts = [] # thread: elenco dei thread
    for r in range(rows): 
        s.append(Event())
        ts.append(Thread(target=Scroller, args=(r, s[r], q, blck_q,), daemon=True))
        if r != 0: # salto la prima riga, che avrà sempre testo statico
            ts[r].start()


    ## MAIN
    while not killer.kill_now:
        try:
            newInfo = GetInfo()
            # print(oldInfo)
            # logging.debug(oldInfo)
            # print(newInfo)
            # logging.debug(newInfo)
            
            # aggiorno i risultati, se diversi dai precedenti
            if not same_lists(oldInfo, newInfo):
                oldInfo = newInfo[:] # devo aggiungere [:] per fare una copia della lista. Di default viene creato un puntatore
                UpdateDisplay(newInfo, q, blck_q, s)
                
            sleep(data_refresh_rate) #inattivo per x secondi
            
        
        except KeyboardInterrupt:
            lcd.close(clear=True)
            logging.info("Terminato dall'utente, uscita forzata")
            sys.exit(130)
        
    # è intervenuto un SIGTERM ma l'abbiamo intercettato. Graceful exit:
    lcd.close(clear=True)
    logging.info("Arresto del sistema, uscita forzata")

