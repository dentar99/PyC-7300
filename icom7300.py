#! /usr/bin/env python3
""" icom7300.py control an icom ic-7300 radio via serial port """
# pylint: disable=C0302
#
# Author: Tom N4LSJ -- EXPERIMENTAL CODE ONLY FOR TINKERING
#
# INSTRUCTIONS:
#
#    By using this program, you agree it is at your own risk.
#    What works great on my computer may work horribly on yours.
#
#    Back up your radio to SD card in radio's slot before proceeding.
#
#    This program needs python 3 to run.  It will not work with
#    python 2.  You may have to install some python modules to
#    get it to work.  The most likely module you'll need to
#    install is pyserial, with pip3 install pyserial
#
# EVERYTHING IN THE COMMENTS BELOW THIS LINE IS EXPERIMENTAL
#
# DEFAULT TCP/IP PORT NUMBERS FOR PYCOM SUITE
#
# WEB BROWSER MAP   7521
# WEB BROWSER AUD   7522
# WEB MAP QSY       7523
# LOGGER READ CI-V  7524
#
# WHY ALL THE PORTS?  This is in case you're running all programs on the same machine.
#
# NETWORK CHAIN W/PyCOM-7300 and WEB BROWSER
#
# WEB BROWSER -> (HTTP) 7521 -> PYSKIMMER -> (QSY) 7523 -> PyCOM-7300

# PYSKIMMER may run on a separate machine
# PyCOM-7300 may run on a separate or third as well
# PyCOM-7300 must be the one connected to the radio via its serial/usb port
# You may run all these on the same machine if the CPU will allow it.
#
# N3FJP or SKCC LOGGER can read the radio's frequency via CI-V by emulating the serial port.
# set up n3fjp 115200 COM4 Icom2 FE FE 94 E0 03 FD and FE FE 94 E0 04 FD
# or skcc logger 115200 etc...
#
# In WINDOWS LAND
# LOGGER -> com0com/COM4->com0com/cncb0 -> com2tcp --ignore-dsr --baud 115200 \\.\cncb0 IPADDR-PyC-7300 7524
# (may or may not also need --telnet option)
# (talks in CI-V language directly)
#
# In LINUX LAND
# LOGGER -> /usr/bin/socat -W /tmp/logger_socket -d -d pty,link=/dev/ttyS0,b115200,cfmakeraw,mode=666,group-late=dialout TCP:(PyCOM-7300 IP):7523
#
#


import sys
import math
import textwrap
import collections
import time
import multiprocessing
# import queue
import tkinter
import tkinter.ttk
import tkinter.messagebox
import tkinter.simpledialog
import os
import shutil
import serial.tools.list_ports
if os.name == 'posix':
    import termios
    import fcntl
import struct
import socket
import select

class Socky:
    def __init__(self,host,port,listen_instead):
        if listen_instead:
            self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            self.s.bind((host,port))
            self.s.listen()
        else:
            self.s = socket.create_connection((host,port))
        self.s.setblocking(0)
        self.conn=None
        self.data=None
        self.addr=None
        self.rx_until = b''

    def accept(self):
        try:
            #print("a",end='',flush=True)
            self.conn, self.addr = self.s.accept()
        except:
            pass

    def non_blocking_rx_until(self,expected):
        bb=self.rxdata()
        if bb is not b'' and bb is not None:
            self.rx_until += bb
        if bb == expected:
            retval = self.rx_until
            self.rx_until = b''
            return retval
        return None

    def rxdata(self):
        if self.conn is None:
            self.accept()
        if self.conn is not None:
            try:
                self.ready_to_read, self.ready_to_send, self.in_error = \
                    select.select([self.conn,], [self.conn,], [], .1)
            except select.error:
                try:
                    self.conn.shutdown(2)
                    self.conn.close()
                    print("conn: select error in rxdata...")
                except:
                    print("Disconnected from other end")
                self.conn=None

            if len(self.in_error) > 0:
                print("conn: socket error in rxdata...")

            if len(self.ready_to_read) > 0:
                #print(str(self.ready_to_read)+"R ", flush=True)
                try:
                    recv = self.conn.recv(1)
                except:
                    recv = b''

                if recv == b'':
                    try:
                        self.shut()
                    except:
                        print("Disconnected from other end")
                    self.conn=None
                    return None
                else:
                    return recv
            else:
                return None
        else:
            return None

    def sxdata(self,data):
        if self.conn is None:
            self.accept()
        if self.conn is not None:
            try:
                self.ready_to_read, self.ready_to_send, self.in_error = \
                    select.select([self.conn,], [self.conn,], [], .1)
            except select.error:
                self.shut()
                print("conn: select error in sxdata...")

            if len(self.in_error) > 0:
                print("conn: socket error in sxdata...")

            if len(self.ready_to_send) > 0 and data is not None:
                try:
                    self.conn.send(data)
                except:
                    self.shut()
                    return None
        else:
            return None

    def shut(self):
        try:
            self.conn.shutdown(2)
            self.conn.close()
            self.conn=None
        except:
            print("Could not shut down socket, already closed?")



def _gdp_can(cc):
    ICOM.digiprog.set('')


def _gdp_go(cc):
    ICOM.digiprog.set(cc.get())


def get_digi_prog():
    digiprogs=list()
    digiprog=tkinter.StringVar()
    for z in ('wsjtx','jtdx','fldigi','flrig','js8call'):
        x=shutil.which(z)
        if x is not None:
            digiprogs.append(x)

    if len(digiprogs) > 0:
        digi_win = tkinter.Toplevel(root)
        #cc = tkinter.ttk.Combobox(digi_win, values=digiprogs, height=1)
        cc = tkinter.Listbox(digi_win,  height=len(digiprogs))
        cc['selectmode']=tkinter.SINGLE
        for x in digiprogs:
            cc.insert(tkinter.END,x)
        cc.grid(row=1,column=1,columnspan=2)
        b_b=tkinter.Button(digi_win,text="Go")
        b_b.grid(row=2,column=1)
        c_b=tkinter.Button(digi_win,text="Cancel")
        c_b.grid(row=2,column=2)
        digi_win.bind('<Escape>',lambda x=0: digiprog.set("0"))
        c_b.bind('<ButtonRelease-1>',lambda x=0: digiprog.set("0"))
        b_b.bind('<ButtonRelease-1>',lambda x=1: digiprog.set("1"))
        digi_win.grab_set()
        digi_win.wait_variable(digiprog)
        #print("digiprog is "+str(digiprog.get()))
        if digiprog.get() == "1":
            print(cc.curselection())
            if len(cc.curselection()) == 0:
                digi_win.destroy()
                return None
            tmp=digiprogs[cc.curselection()[0]]
            digi_win.destroy()
            if tmp == "":
                return None
            else:
                return tmp
        elif digiprog.get() == "0":
            digi_win.destroy()
            return None
        else:
            print("HUH?")
            return None
    else:
        tkinter.messagebox.showerror(
            title="D'oh!",
            message="I can not find any programs.")
        return None

def erase_status_line():
    ICOM.status_line.set("")

def setting_get(command):
    CO.send_direct(ICOM.send_preamble_bin + ICOM.binary_send_item[command] + ICOM.suffix_bin)
    retval = CO.no_buf_direct_receive()
    print("command was "+command)
    return((command,retval))

def setting_get_and_set(command,val):
    CO.send_direct(ICOM.send_preamble_bin + ICOM.binary_send_item[command] + ICOM.suffix_bin)
    retval = CO.no_buf_direct_receive()
    CO.send_direct(ICOM.send_preamble_bin + ICOM.binary_send_item[command] + val + ICOM.suffix_bin)
    garbage = CO.no_buf_direct_receive()
    CO.send_direct(ICOM.send_preamble_bin + ICOM.binary_send_item[command] + ICOM.suffix_bin)
    newval = CO.no_buf_direct_receive()
    #print(" ")
    print("command was "+command)
    if retval is not None:
        print("retval was "+retval.hex())
        #print("garbage was "+garbage.hex())
    if newval is not None:
        print("newval was "+newval.hex())
    return((command,retval))


def stuff_startup_cmds():
    # FIRST we stuff mandatory commands into the queue to put it into VFO mode,
    # select "A", turn off Echo, and turn off Transceive
    # turn off scope sending
    CO.send_direct(ICOM.send_preamble_bin + b'\x27\x11\x00' + ICOM.suffix_bin)
    # switch to vfo mode
    CO.send_direct(ICOM.send_preamble_bin + b'\x07' + ICOM.suffix_bin)
    # switch to vfo A
##    CO.send_direct(ICOM.send_preamble_bin + b'\x07\x00' + ICOM.suffix_bin)
    # turn off echo back
    CO.send_direct(ICOM.send_preamble_bin + b'\x1a\x05\x00\x75\x00' + ICOM.suffix_bin)
    # turn off ci-v transceive
    CO.send_direct(ICOM.send_preamble_bin + b'\x1a\x05\x00\x71\x00' + ICOM.suffix_bin)

def start_scope_send():
    if ICOM.scopewin.winfo_ismapped():
        CO.send_direct(ICOM.send_preamble_bin + b'\x27\x10\x01' + ICOM.suffix_bin) # be sure scope in radio is on
        CO.send_direct(ICOM.send_preamble_bin + b'\x27\x11\x01' + ICOM.suffix_bin) # tell radio to stream scope to window

def stop_scope_send():
    if ICOM.scopewin.winfo_ismapped():
        CO.send_direct(ICOM.send_preamble_bin + b'\x27\x11\x00' + ICOM.suffix_bin) # tell radio to stream scope to window
        # repeat to make sure
        CO.send_direct(ICOM.send_preamble_bin + b'\x27\x11\x00' + ICOM.suffix_bin) # tell radio to stream scope to window

### ask yes no
def _askyesno(title= "", message= "" , *args):
    CO.pauseq.put('pause', True)
    stop_scope_send()
    qq=_replfunc_askyesno(title=title, message=message, *args)
    dummy=CO.pauseq.get()
    start_scope_send()
    return qq

_replfunc_askyesno = tkinter.messagebox.askyesno
tkinter.messagebox.askyesno = _askyesno

## showerror
def _showerror(title= "", message= "" , *args):
    CO.pauseq.put('pause', True)
    stop_scope_send()
    qq=_replfunc_showerror(title=title, message=message, *args)
    dummy=CO.pauseq.get()
    start_scope_send()
    return qq

_replfunc_showerror = tkinter.messagebox.showerror
tkinter.messagebox.showerror = _showerror

## showwarning
def _showwarning(title= "", message= "" , *args):
    CO.pauseq.put('pause', True)
    stop_scope_send()
    qq=_replfunc_showwarning(title=title, message=message, *args)
    dummy=CO.pauseq.get()
    start_scope_send()
    return qq

_replfunc_showwarning = tkinter.messagebox.showwarning
tkinter.messagebox.showwarning = _showwarning

def get_meter_255(meter_name,mtr):

    if meter_name == 'swr_meter':
        xxtbl = ICOM.swrtbl

    if meter_name == 'po_meter':
        xxtbl = ICOM.pwrtbl

    for i in range(0,len(xxtbl)):
        try:
            if (mtr >= xxtbl[i][0] and mtr < xxtbl[i+1][0]):
                break
        except:
            i = i - 1
            break

    mtr = int(math.ceil( xxtbl[i][1] + (xxtbl[i+1][1] - xxtbl[i][1])*(mtr - xxtbl[i][0]) / (xxtbl[i+1][0] - xxtbl[i][0])))
    
    if mtr > 100:
        mtr = 100
    if mtr < 0:
        mtr = 0

    return mtr

def hide_scope(*args):
    CO.send_direct(ICOM.send_preamble_bin + b'\x27\x11\x00' + ICOM.suffix_bin) # tell radio to stop streaming scope
    CO.send_direct(ICOM.send_preamble_bin + b'\x27\x11\x00' + ICOM.suffix_bin) # tell radio to stop streaming scope
    ICOM.scopewin.update()
    ICOM.scopewin.withdraw()

def show_scope(*args):
    ICOM.scopewin.deiconify()
    ICOM.scopewin.update()
    CO.send_direct(ICOM.send_preamble_bin + b'\x27\x10\x01' + ICOM.suffix_bin) # be sure scope in radio is on
    CO.send_direct(ICOM.send_preamble_bin + b'\x27\x11\x01' + ICOM.suffix_bin) # tell radio to stream scope to window

def timesync(*args):
    """ sets var to true upon pressing something """
    # pylint: disable=W0613

    if time.timezone == 0.0:
        tfunc = time.localtime
    else:
        t_z = tkinter.messagebox.askyesno(
            title="Time Zone!",
            message="Answer YES to set radio to computer clock, " \
                    +"or NO to set to UTC based on computer clock.  " \
                    +"It is assumed your PC clock is local.")
        if t_z:
            tfunc = time.localtime
        else:
            tfunc = time.gmtime

    t_l = tfunc()
    while t_l.tm_sec > 0:
        t_l = tfunc()
        ICOM.widget_object['timesync'].config(text=str(t_l.tm_sec))
        if CO.quitq.empty():
            # keep this receivecycle
            receivecycle()
        else:
            return

    ICOM.widget_object['timesync'].config(text='Time Sync')

    datestr = ('0000'+str(t_l.tm_year))[-4:] \
               +('00'+str(t_l.tm_mon))[-2:] \
               +('00'+str(t_l.tm_mday))[-2:]

    timestr = ('00'+str(t_l.tm_hour))[-2:]+('00'+str(t_l.tm_min))[-2:]

    g_o = t_l.tm_gmtoff
    gmtdigs = ('0000'+str(abs(int(g_o/3600*100))))[-4:]
    if g_o < 0:
        gmtdigs += '01'
    else:
        gmtdigs += '00'

    datestr_b = CO.send_preamble_bin+bytes.fromhex('1a050094'+datestr)+CO.suffix_bin
    timestr_b = CO.send_preamble_bin+bytes.fromhex('1a050095'+timestr)+CO.suffix_bin
    gmtdigs_b = CO.send_preamble_bin+bytes.fromhex('1a050096'+gmtdigs)+CO.suffix_bin
    CO.send_direct(datestr_b)
    CO.send_direct(timestr_b)
    CO.send_direct(gmtdigs_b)


#def pressed(*args):
#    """ sets var to true upon pressing something """
#    # pylint: disable=W0613
#    ICOM.gui_touched = time.time()
#    ICOM.button_pressed = True

#def pressed_time(event,tt,*args):
#    """ sets var to true upon pressing something with a time limit """
#    # pylint: disable=W0613
#    ICOM.gui_touched = time.time()
#    ICOM.button_pressed = True
#    root.after(tt, released)

#def released(*args):
#    """ sets var to false upon releasing """
#    # pylint: disable=W0613
#    ICOM.gui_touched = time.time()
#    ICOM.button_pressed = False


def _process_logger(cmd_dict, received_data):
    ICOM.status_line.set(cmd_dict['name'])
    root.update()
    root.after(500,erase_status_line)

def _process_keyer_send(cmd_dict, received_data):
    """ process specific thing """
    returnval = received_data[ICOM.irpl+len(cmd_dict['command']) \
        :ICOM.irpl +len(cmd_dict['command'])+(cmd_dict['num_of_bytes_returned'])]
    slot = returnval[0:1]
    aslot = str(slot)
    # THIS fromhex is OK to keep
    asciimsg = returnval[1:].decode()
    ICOM.cw_keyer[slot] = asciimsg
    if slot not in ICOM.cw_keyer_edit:
        ICOM.cw_keyer_edit[slot] = tkinter.StringVar()
    ICOM.cw_keyer_edit[slot].set(asciimsg.rstrip())
    ICOM.widget_object[cmd_dict['name']+aslot].configure(text=asciimsg[0:5])
    if slot not in ICOM.cw_keyer_tip:
        ICOM.cw_keyer_tip[slot]=CreateToolTip(ICOM.widget_object[cmd_dict['name']+aslot], asciimsg)
    else:
        if ICOM.cw_keyer_tip[slot].text is not None:
            ICOM.cw_keyer_tip[slot].text=asciimsg

def _process_scale0255_progressbar(cmd_dict, received_data):
    """ process specific thing """
    widg = ICOM.widget_object[cmd_dict['name']]
    returnval = received_data[ICOM.irpl+len(cmd_dict['command']) \
        :ICOM.irpl +len(cmd_dict['command'])+(cmd_dict['num_of_bytes_returned'])]
    vals = list(widg.values)
    if cmd_dict['name'] in ('swr_meter','po_meter'):
        w_val = get_meter_255(cmd_dict['name'], int(returnval.hex()))
    else:
        w_val = int((((int(returnval.hex()) + widg.bias) \
            / (254 - widg.bias)) * (vals[-1] - vals[0])) + vals[0])
    #if widg.type == 'Progressbar':
    ICOM.widget_variable[cmd_dict['name']].set(w_val)
    ICOM.last_polled_value[cmd_dict['name']].set(w_val)
    ICOM.widget_object[cmd_dict['name']].update()

def _process_scaleff(cmd_dict, received_data):
    """ process specific thing """
    widg = ICOM.widget_object[cmd_dict['name']]
    returnval = received_data[ICOM.irpl+len(cmd_dict['command']) \
        :ICOM.irpl +len(cmd_dict['command'])+(cmd_dict['num_of_bytes_returned'])]
    w_val = int(returnval.hex())+widg.bias
    ICOM.widget_variable[cmd_dict['name']].set(w_val)
    ICOM.last_polled_value[cmd_dict['name']].set(w_val)
    ICOM.widget_object[cmd_dict['name']].update()

def _process_mdfset(cmd_dict, received_data):
    """ process specific thing """
    returnval = received_data[ICOM.irpl+len(cmd_dict['command']) \
        :ICOM.irpl +len(cmd_dict['command'])+(cmd_dict['num_of_bytes_returned'])]
    if returnval.hex() == "fffd":
        return
    #print("MDFSET: "+returnval.hex())
    # pylint: disable=W0632
    [mode, data, fil] = textwrap.wrap(returnval.hex(), 2)
    #if not ICOM.button_pressed:
    ICOM.widget_variable[cmd_dict['name']+'m'].set(mode)
    ICOM.widget_variable[cmd_dict['name']+'d'].set(data)
    ICOM.widget_variable[cmd_dict['name']+'f'].set(fil)
    ICOM.last_polled_value[cmd_dict['name']+'m'].set(mode)
    ICOM.last_polled_value[cmd_dict['name']+'d'].set(data)
    ICOM.last_polled_value[cmd_dict['name']+'f'].set(fil)
    for m in ICOM.modes:
        ICOM.widget_object[cmd_dict['name']+'m'+ICOM.modes[m]].update()
    ICOM.widget_object[cmd_dict['name']+'d'].update()
    for f in '123':
        ICOM.widget_object[cmd_dict['name']+'f'+f].update()

def _process_scope_edge(cmd_dict, received_data):
    """ process specific thing """
    returnval = received_data[ICOM.irpl+len(cmd_dict['command']) \
        :ICOM.irpl +len(cmd_dict['command'])+(cmd_dict['num_of_bytes_returned'])]
    ICOM.widget_object['scope_edge'].set(returnval.hex()[-2:])
    #print("scope edge returnval is "+str(returnval))
    ICOM.widget_object['scope_edge'].update()


def _process_scope_width(cmd_dict, received_data):
    """ process specific thing """
    returnval = received_data[ICOM.irpl+len(cmd_dict['command']) \
        :ICOM.irpl +len(cmd_dict['command'])+(cmd_dict['num_of_bytes_returned'])]
    print("scope width returnval is "+str(returnval))

def _process_vfoset(cmd_dict, received_data):
    """ process specific thing """
    returnval = received_data[ICOM.irpl+len(cmd_dict['command']) \
        :ICOM.irpl +len(cmd_dict['command'])+(cmd_dict['num_of_bytes_returned'])]
    if root.IN_ENTRY or returnval.hex() == "fffd":
        return
    w_v = "{:010,}".format(int(returnval[::-1].hex())).replace(',', '.')
    ICOM.last_polled_value[cmd_dict['name']].set(w_v)
    if time.time() - ICOM.vfo_touched > 10:
        ICOM.widget_variable[cmd_dict['name']].set(w_v)
        ICOM.widget_object[cmd_dict['name']].update()

def _process_ovf(cmd_dict, received_data):
    """ process specific thing """
    returnval = received_data[ICOM.irpl+len(cmd_dict['command']) \
        :ICOM.irpl +len(cmd_dict['command'])+(cmd_dict['num_of_bytes_returned'])]
    ICOM.widget_object['ovfb'].config(fg={'00':'black','01':'red'}[returnval.hex()])
    ICOM.widget_object['ovfb'].update()

def _process_radio_date(cmd_dict, received_data):
    """ process specific thing """
    rvh = received_data[ICOM.irpl+len(cmd_dict['command']) \
        :ICOM.irpl +len(cmd_dict['command'])+(cmd_dict['num_of_bytes_returned'])].hex()
    ICOM.radio_date.set( rvh[0:4]+'/'+rvh[4:6]+'/'+rvh[6:8])
    ICOM.widget_object['datedisp'].update()


def _process_radio_time(cmd_dict, received_data):
    """ process specific thing """
    rvh = received_data[ICOM.irpl+len(cmd_dict['command']) \
        :ICOM.irpl +len(cmd_dict['command'])+(cmd_dict['num_of_bytes_returned'])].hex()
    ICOM.radio_time.set(
        rvh[0:2]+':'+ rvh[2:4]+'/'+ ICOM.radio_tz.get())
    ICOM.widget_object['timedisp'].update()

def _process_radio_tz(cmd_dict, received_data):
    """ process specific thing """
    returnval = received_data[ICOM.irpl+len(cmd_dict['command']) \
        :ICOM.irpl +len(cmd_dict['command'])+(cmd_dict['num_of_bytes_returned'])]
    tzs={'00':'+','01':'-','00':'+'}[returnval.hex()[4:6]]
    ICOM.radio_tz.set(tzs+returnval.hex()[0:4])
    ICOM.widget_object['timedisp'].update()

def _process_my_call(cmd_dict, received_data):
    """ process specific thing """
    returnval = received_data[ICOM.irpl+len(cmd_dict['command']) \
        :ICOM.irpl +len(cmd_dict['command'])+(cmd_dict['num_of_bytes_returned'])]
    mycall = returnval.decode().strip()
    root.title('PyC-7300: '+mycall)
    ICOM.my_call_sign.set(mycall)
    ICOM.widget_object['callbrag'].update()

def _process_contest_num(cmd_dict, received_data):
    """ process specific thing """
    returnval = received_data[ICOM.irpl+len(cmd_dict['command']) \
        :ICOM.irpl +len(cmd_dict['command'])+(cmd_dict['num_of_bytes_returned'])]
    cnum = int(returnval[0:2].hex())
    fmt={True:"{:04d}",False:"{:03d}"}[cnum>999].format(cnum)
    ICOM.widget_variable[cmd_dict['name']].set(fmt)
    ICOM.last_polled_value[cmd_dict['name']].set(fmt)
    ICOM.widget_object[cmd_dict['name']].update()

def _process_rit_freq(cmd_dict, received_data):
    """ process specific thing """
    returnval = received_data[ICOM.irpl+len(cmd_dict['command']) \
        :ICOM.irpl +len(cmd_dict['command'])+(cmd_dict['num_of_bytes_returned'])]
    w_v = float(int(returnval[1:2].hex()+returnval[0:1].hex())/1000)
    if returnval[2:3] == b'\x01':
        w_v = w_v*-1
    w_v = "{:+0.3f}".format(w_v)
    ICOM.widget_variable[cmd_dict['name']].set(w_v)
    ICOM.last_polled_value[cmd_dict['name']].set(w_v)
    ICOM.widget_object[cmd_dict['name']].update()

def _process_mem_ch(cmd_dict, received_data):
    """ process specific thing """
    returnval = received_data[ICOM.irpl+len(cmd_dict['command']) \
        :ICOM.irpl +len(cmd_dict['command'])+(cmd_dict['num_of_bytes_returned'])]
    populate_memch(ICOM.widget_object['set_mem_modebox'], returnval)

def _process_contestnums(cmd_dict, received_data):
    """ process specific thing """
    returnval = received_data[ICOM.irpl+len(cmd_dict['command']) \
        :ICOM.irpl +len(cmd_dict['command'])+(cmd_dict['num_of_bytes_returned'])]
    if returnval != '':
        ICOM.widget_object[cmd_dict['name']].current(int(returnval.hex()))
    ICOM.widget_object[cmd_dict['name']].update()

def _process_cur_rx_bw(cmd_dict, received_data):
    """ process specific thing """
    returnval = received_data[ICOM.irpl+len(cmd_dict['command']) \
        :ICOM.irpl +len(cmd_dict['command'])+(cmd_dict['num_of_bytes_returned'])]
    mode = ICOM.widget_variable['this_vfo_mdfm'].get()
    if mode != '':
        ICOM.widget_object[cmd_dict['name']]['values'] = ICOM.bandwidths[mode]
        ICOM.widget_object[cmd_dict['name']].current(int(returnval.hex()))
    ICOM.widget_object[cmd_dict['name']].update()

def _process_agc_time(cmd_dict, received_data):
    """ process specific thing """
    returnval = received_data[ICOM.irpl+len(cmd_dict['command']) \
        :ICOM.irpl +len(cmd_dict['command'])+(cmd_dict['num_of_bytes_returned'])]
    mode = ICOM.widget_variable['this_vfo_mdfm'].get()
    if mode != '':
        ICOM.widget_object[cmd_dict['name']]['values'] = ICOM.agc[mode]
        ICOM.widget_object[cmd_dict['name']].current(int(returnval.hex()))
    ICOM.widget_object[cmd_dict['name']].update()

def scopewheelms(evt):
    if evt.delta < 0:
        vinc = 236.1
    if evt.delta > 0:
        vinc = 239
    q=evt
    q.x=vinc
    scopeclick(q)
    
def scopewheel(evt,a):
    """ do stuff when scrolling on the scope """
    #print(evt)
    #print(a)
    q=evt
    q.x=a
    scopeclick(q)

def clear_peaks():
    for xaxis in range(0,475):
        #ICOM.scope_canvas.coords( ICOM.scope_peak_line[xaxis], (xaxis, 160, xaxis, 0))
        for y in range(0,20):
            try:
                ICOM.peaks[xaxis].pop()
            except:
                pass

def scopeclickround(evt):
    """ do stuff when clicking on the scope """
    newhz = ICOM.scope_bottom + (ICOM.scope_hzper * evt.x)

    mode = ICOM.widget_variable['this_vfo_mdfm'].get()
    if mode == '03': # cw # round to 500 hz if cw
        roundhz = int(round(newhz*2,-3))/2
    else: # round to 1000 hz if not cw
        roundhz = int(round(newhz,-3))

    qsy = "{:010d}".format(int(roundhz))
    bqsy = ICOM.send_preamble_bin + \
            ICOM.widget_object['this_vfo_freq'].command + \
            bytes.fromhex(qsy)[::-1] + \
            ICOM.suffix_bin
    ICOM.vfo_touched = -99999
    CO.send_direct(bqsy)
    clear_peaks()
    pollvfo()

def scopeclick(evt):
    """ do stuff when clicking on the scope """
    newhz = ICOM.scope_bottom + (ICOM.scope_hzper * evt.x)
    qsy = "{:010d}".format(int(newhz))
    bqsy = ICOM.send_preamble_bin + \
            ICOM.widget_object['this_vfo_freq'].command + \
            bytes.fromhex(qsy)[::-1] + \
            ICOM.suffix_bin

    ICOM.vfo_touched = -99999
    CO.send_direct(bqsy)
    clear_peaks()
    pollvfo()

def _process_color(cmd_dict, received_data):
    rvh = received_data[ICOM.irpl+len(cmd_dict['command']) \
        :ICOM.irpl +len(cmd_dict['command'])+(cmd_dict['num_of_bytes_returned'])].hex()
    name = cmd_dict['name']
    ICOM.scope_color[name] = '#'+hex((int(rvh[0:4])*256*256)+(int(rvh[4:8])*256)+int(rvh[8:12])).replace('0x','').zfill(6)
    linearr={'scope_line_color':ICOM.scope_spectrum_line,'scope_fill_color':ICOM.scope_fill_line,'scope_peak_color':ICOM.scope_peak_line}[name]
    for xaxis in range(0,475):
        ICOM.scope_canvas.itemconfig( linearr[xaxis], fill=ICOM.scope_color[name])

def _process_scope(cmd_dict, received_data):
    """ process specific thing """

    returnval = received_data[ICOM.irpl+len(cmd_dict['command']) \
        :ICOM.irpl +len(cmd_dict['command'])+(cmd_dict['num_of_bytes_returned'])]

    div=returnval[1:2]

    if div == b'\x01':

        if returnval[14:15] != b'\x00': # scope oob
            ICOM.scope_canvas.coords(ICOM.scope_oob_msg,(233,100))
            return
        else:
            ICOM.scope_canvas.coords(ICOM.scope_oob_msg,(0,-20))

        ICOM.scope_c_or_f = returnval[3:4]
        ICOM.scope_one_freq = int(reverse_hex_to_bcd(returnval[4:9].hex()))
        ICOM.scope_two_freq = int(reverse_hex_to_bcd(returnval[9:14].hex()))

        # move all down
        ICOM.waterfall_canvas.move(tkinter.ALL,0,1)
        # get the tag for the top
        ICOM.wafa_top_tag = ICOM.waterfall_canvas.gettags(ICOM.waterfall_canvas.find_overlapping(0,ICOM.wafa_bot,0,ICOM.wafa_bot))
        # move all the ones on the bottom line up
        ICOM.waterfall_canvas.move(ICOM.wafa_top_tag,0,(ICOM.wafa_bot )*-1)

        # THIS WORKS BUT TRYING MOVE TAG
        #for xx in ICOM.wafa_pix[ICOM.wafa_top_tag]:
        #    ICOM.waterfall_canvas.move(ICOM.wafa_pix[ICOM.wafa_top_tag][xx],0,-101)

        ICOM.scope_bot_lbl.set("Bot: "+"{:10,}".format(ICOM.scope_bottom).replace(',','.'))
        ICOM.widget_object['scope_width'].set(ICOM.scope_two_freq)
        if ICOM.scope_c_or_f == b'\x00':
            ICOM.scope_bottom = ICOM.scope_one_freq - ICOM.scope_two_freq
            ICOM.scope_hzper = ( ICOM.scope_two_freq * 2 / 475 )
            ICOM.widget_object['scope_width'].grid()
            ICOM.widget_object['scope_edge'].grid_remove()
            ICOM.scope_top_lbl.set("Top: "+"{:10,}".format(ICOM.scope_one_freq + ICOM.scope_two_freq).replace(',','.'))
            ICOM.widget_object['scope_c_or_f'].config(text='Center')

        elif ICOM.scope_c_or_f == b'\x01':
            ICOM.scope_bottom = ICOM.scope_one_freq
            ICOM.scope_hzper = ((ICOM.scope_two_freq - ICOM.scope_bottom) / 475)
            ICOM.widget_object['scope_width'].grid_remove()
            ICOM.widget_object['scope_edge'].grid()
            ICOM.scope_top_lbl.set("Top: "+"{:10,}".format(ICOM.scope_two_freq).replace(',','.'))
            ICOM.widget_object['scope_c_or_f'].config(text='Fixed')

        sm=ICOM.widget_object['scope_mult'].get()

        #if sm == "":
        #    ICOM.widget_object['scope_mult'].set("x1")

        ICOM.scope_mult = {"":1, "x1":1, "x2":2, "x4":4, "x8":8}[sm]

        this=ICOM.widget_variable['this_vfo_freq'].get().replace('.','')
        that=ICOM.widget_variable['that_vfo_freq'].get().replace('.','')

        if not (this == '' or that == ''):
            split=ICOM.widget_variable['split_on_off'].get()
            rx_x = int((int(this) - int(ICOM.scope_bottom)) / ICOM.scope_hzper)
            if split == str(b'\x01'):
                tx_x = int((int(that) - int(ICOM.scope_bottom)) / ICOM.scope_hzper)
            else:
                tx_x = rx_x

            # have to test separately here, sorry
            ICOM.scope_canvas.coords( ICOM.scope_receive_freq,  (rx_x, {True:80,False:0}[rx_x==tx_x], rx_x, 160))
            ICOM.scope_canvas.coords( ICOM.scope_transmit_freq, (tx_x, 0,                             tx_x, 160))

        ICOM.scopewin.update()


    if div != b'\x01':
    # we don't "get" all the way to x11 when scope is outta band so we don't worry about it!
        # this is the "starting position"
        xaxis=(int(div.hex()) - 2)*50

        #ftn = ICOM.waterfall_canvas.gettags(ICOM.waterfall_canvas.find_closest(0,0,0))[0].replace('t','')

        for py in returnval[3:-1]:
            #print("py is "+str(py))
            amplitude = 160 - min(py * ICOM.scope_mult,159)
            #amplitude=160-yaxis

            ICOM.peaks[xaxis].append(amplitude)
            # set peak lengths
            if len(ICOM.peaks[xaxis]) > 10:
                ICOM.peaks[xaxis].pop(0)
            mp=min(ICOM.peaks[xaxis])

            if ICOM.prevpeak[xaxis] != mp:
                ICOM.scope_canvas.coords(ICOM.scope_peak_line[xaxis],(xaxis,160,xaxis,mp))
                ICOM.prevpeak[xaxis]=mp

            # set position of main line
            if xaxis > 0:
                if ICOM.prevline[xaxis] != (ICOM.prevyaxis[xaxis-1],amplitude):
                    ICOM.scope_canvas.coords(ICOM.scope_spectrum_line[xaxis], (xaxis-1, ICOM.prevyaxis[xaxis-1], xaxis, amplitude))
                    ICOM.prevline[xaxis]=(ICOM.prevyaxis[xaxis-1],amplitude)

            # set length of fill line
            if ICOM.prevyaxis[xaxis] != amplitude:
                ICOM.scope_canvas.coords(ICOM.scope_fill_line[xaxis], (xaxis, 160,   xaxis, amplitude))
                ICOM.prevyaxis[xaxis]=amplitude

            # set the color for that one pixel on the waterfall
            #ICOM.waterfall_canvas.itemconfigure(ICOM.wafa_pix[ftn][xaxis],fill=ICOM.yaxcolor[amplitude])
            ICOM.waterfall_canvas.itemconfigure(ICOM.wafa_pix[ICOM.wafa_top_tag[0].replace('t','')][xaxis],
                fill=ICOM.yaxcolor[amplitude])

            xaxis+=1

        if os.name == 'nt':
            ICOM.scopewin.update()


def _process_other(cmd_dict, received_data):
    """ process specific thing """
    returnval = received_data[ICOM.irpl+len(cmd_dict['command']) \
        :ICOM.irpl +len(cmd_dict['command'])+(cmd_dict['num_of_bytes_returned'])]
    if cmd_dict['name'] not in ICOM.widget_variable.keys():
        print("No " + cmd_dict['name'] + " for widget_variable")
        print("received data is "+received_data.hex())
        pass
    else:
        ICOM.widget_variable[cmd_dict['name']].set(returnval)
        ICOM.last_polled_value[cmd_dict['name']].set(returnval)

def _process_nothing(cmd_dict, received_data):
    """ process specific thing """
    # pylint: disable=W0613
    print("Processing Nothing for "+cmd_dict['name'])
    return None

class images():
    """ images for the program in base64 """
    def __init__(self):
        self.swr_base64="""
iVBORw0KGgoAAAANSUhEUgAAAPsAAAATCAYAAABWZXtJAAABhGlDQ1BJQ0MgcHJvZmlsZQAAKJF9
kT1Iw0AcxV9bRZEWByOIOGSoThZERR21CkWoEGqFVh1MLv2CJg1Jiouj4Fpw8GOx6uDirKuDqyAI
foA4OTopukiJ/0sKLWI8OO7Hu3uPu3dAsF5mmtUxBmi6baYScTGTXRW7XhGCgAim0S8zy5iTpCR8
x9c9Any9i/Es/3N/joiasxgQEIlnmWHaxBvEU5u2wXmfWGBFWSU+Jx416YLEj1xXPH7jXHA5yDMF
M52aJxaIxUIbK23MiqZGPEkcVTWd8oMZj1XOW5y1cpU178lfGM7pK8tcpzmEBBaxBAkiFFRRQhk2
YrTqpFhI0X7cxz/o+iVyKeQqgZFjARVokF0/+B/87tbKT4x7SeE40PniOB/DQNcu0Kg5zvex4zRO
gNAzcKW3/JU6MPNJeq2lRY+A3m3g4rqlKXvA5Q4w8GTIpuxKIZrBfB54P6NvygJ9t0DPmtdbcx+n
D0CaukreAAeHwEiBstd93t3d3tu/Z5r9/QCCAXKtRPfxFgAAAAZiS0dEAP8A/wD/oL2nkwAAAAlw
SFlzAAAOxAAADsQBlSsOGwAAAAd0SU1FB+QDFA4ZG8IhBNIAAAAZdEVYdENvbW1lbnQAQ3JlYXRl
ZCB3aXRoIEdJTVBXgQ4XAAABWElEQVR42u2a0W3EIAyGfVEX6ggdofP04TgpnacjdISORF+KlCKc
0kjYFnyfdBLHy28wfzAkt7SnLCJyf7vL88uriIh8fX7Qpk17svYmALAEmB0AswMAZgcAzA4AmB0A
HLkdX7158Xh/iGcM6Pvqg7HZAWBys+ecMTvAAjzV5ZxVKadplZLyyMiYjnoWY/9Lb/bxX4mnXivl
fz1XKx1DtLyd5jP/kPaU056yBWdaVjG0tEZr9+jNPP6r8fy3f3auzscWZUf3wDqOaDtP9J2QC8M+
/5QqR+v/VcZbTmqPVrTSMkqJNlrPe67rxYnZB57ZIz7NrSoB64pD0/MYv3Y29s5/Tzw8HPrho5pA
Rof+iudo8JXmsnUxqV1Y1utsi5LEEmgrobMb3Wv81nM9Mp7WYp/d8OVX1pPWH7qMtyrNWgbz1rMc
f7Qz8lk82u61KlquznLIRzUAi/ANiO6htKkrwZ8AAAAASUVORK5CYII=
"""

        self.pwr_base64="""
iVBORw0KGgoAAAANSUhEUgAAAPsAAAATCAYAAABWZXtJAAABhGlDQ1BJQ0MgcHJvZmlsZQAAKJF9
kT1Iw0AcxV9bRZEWByOIOGSoThZERR21CkWoEGqFVh1MLv2CJg1Jiouj4Fpw8GOx6uDirKuDqyAI
foA4OTopukiJ/0sKLWI8OO7Hu3uPu3dAsF5mmtUxBmi6baYScTGTXRW7XhGCgAim0S8zy5iTpCR8
x9c9Any9i/Es/3N/joiasxgQEIlnmWHaxBvEU5u2wXmfWGBFWSU+Jx416YLEj1xXPH7jXHA5yDMF
M52aJxaIxUIbK23MiqZGPEkcVTWd8oMZj1XOW5y1cpU178lfGM7pK8tcpzmEBBaxBAkiFFRRQhk2
YrTqpFhI0X7cxz/o+iVyKeQqgZFjARVokF0/+B/87tbKT4x7SeE40PniOB/DQNcu0Kg5zvex4zRO
gNAzcKW3/JU6MPNJeq2lRY+A3m3g4rqlKXvA5Q4w8GTIpuxKIZrBfB54P6NvygJ9t0DPmtdbcx+n
D0CaukreAAeHwEiBstd93t3d3tu/Z5r9/QCCAXKtRPfxFgAAAAZiS0dEAP8A/wD/oL2nkwAAAAlw
SFlzAAAOxAAADsQBlSsOGwAAAAd0SU1FB+QDFA4bFo6mGu0AAAAZdEVYdENvbW1lbnQAQ3JlYXRl
ZCB3aXRoIEdJTVBXgQ4XAAABAklEQVR42u2awRGCMBBFF4aGLMESrMcDyQzUYwmWYEnxok6IRBll
Rtn/3ilwyt/lZ5MsTRhCMjPrj73t9gczM7ucT4wZM3Y2bg0AJMDsAJgdADA7AGB2AMDsAPBDmrz1
pkocoynHQF2/Sn4fZgcA55U9pYTZAQTo5sq99y3dnM78necYvNLpIf+lvlzH1vXFMS7SU9WZboQh
pJzy2Qs1nV71vtPvLf9L87s1fWEIkzl/olPuNp5LKNh6RV9lG09QdY8x4L9AdermvgeyDOhaq+m/
fzgedbKYYXYJMwMGr9Fi9OdqoHJUAS0mfXaF7Y/31tM321wvrbfa3NVbb/xUAyDCFVi4RCjO+Ehd
AAAAAElFTkSuQmCC
"""

        self.alc_base64="""
iVBORw0KGgoAAAANSUhEUgAAAPsAAAATCAYAAABWZXtJAAABhGlDQ1BJQ0MgcHJvZmlsZQAAKJF9
kT1Iw0AcxV9bRZEWByOIOGSoThZERR21CkWoEGqFVh1MLv2CJg1Jiouj4Fpw8GOx6uDirKuDqyAI
foA4OTopukiJ/0sKLWI8OO7Hu3uPu3dAsF5mmtUxBmi6baYScTGTXRW7XhGCgAim0S8zy5iTpCR8
x9c9Any9i/Es/3N/joiasxgQEIlnmWHaxBvEU5u2wXmfWGBFWSU+Jx416YLEj1xXPH7jXHA5yDMF
M52aJxaIxUIbK23MiqZGPEkcVTWd8oMZj1XOW5y1cpU178lfGM7pK8tcpzmEBBaxBAkiFFRRQhk2
YrTqpFhI0X7cxz/o+iVyKeQqgZFjARVokF0/+B/87tbKT4x7SeE40PniOB/DQNcu0Kg5zvex4zRO
gNAzcKW3/JU6MPNJeq2lRY+A3m3g4rqlKXvA5Q4w8GTIpuxKIZrBfB54P6NvygJ9t0DPmtdbcx+n
D0CaukreAAeHwEiBstd93t3d3tu/Z5r9/QCCAXKtRPfxFgAAAAZiS0dEAP8A/wD/oL2nkwAAAAlw
SFlzAAAOxAAADsQBlSsOGwAAAAd0SU1FB+QDFA4eGBRpw68AAAAZdEVYdENvbW1lbnQAQ3JlYXRl
ZCB3aXRoIEdJTVBXgQ4XAAAAwElEQVR42u3bsQ3CMBAF0B+UNagRJSMwAvNQRBTMwwgZISWiZhBT
gVAENBQk+L3qZLk66cfnRGlKKSXA31toAQg7IOyAsAPCDvxOmySb7S5JMvQntVo9sXroT0mSw/Hw
CG637x5r93psvL/1vIPpG4f6U8jf7TfGQwW6fSfsUNWdHZjHKC/sUMko/k3wjfFQyVTQ+BEG5hHW
V2/jX53wz5/lnteaUkq5LNe6SZJkdT1rwp9yskMl3NlB2AFhB2bnBq8LJDh9L2poAAAAAElFTkSu
QmCC
"""

        self.s_base64="""
iVBORw0KGgoAAAANSUhEUgAAAPsAAAATCAYAAABWZXtJAAABhGlDQ1BJQ0MgcHJvZmlsZQAAKJF9
kT1Iw0AcxV9bRZEWByOIOGSoThZERR21CkWoEGqFVh1MLv2CJg1Jiouj4Fpw8GOx6uDirKuDqyAI
foA4OTopukiJ/0sKLWI8OO7Hu3uPu3dAsF5mmtUxBmi6baYScTGTXRW7XhGCgAim0S8zy5iTpCR8
x9c9Any9i/Es/3N/joiasxgQEIlnmWHaxBvEU5u2wXmfWGBFWSU+Jx416YLEj1xXPH7jXHA5yDMF
M52aJxaIxUIbK23MiqZGPEkcVTWd8oMZj1XOW5y1cpU178lfGM7pK8tcpzmEBBaxBAkiFFRRQhk2
YrTqpFhI0X7cxz/o+iVyKeQqgZFjARVokF0/+B/87tbKT4x7SeE40PniOB/DQNcu0Kg5zvex4zRO
gNAzcKW3/JU6MPNJeq2lRY+A3m3g4rqlKXvA5Q4w8GTIpuxKIZrBfB54P6NvygJ9t0DPmtdbcx+n
D0CaukreAAeHwEiBstd93t3d3tu/Z5r9/QCCAXKtRPfxFgAAAAZiS0dEAP8A/wD/oL2nkwAAAAlw
SFlzAAAOxAAADsQBlSsOGwAAAAd0SU1FB+QDFA4aCG2yFs8AAAAZdEVYdENvbW1lbnQAQ3JlYXRl
ZCB3aXRoIEdJTVBXgQ4XAAABm0lEQVR42u2aTU7DMBCFncjHgDWw5AgcgfOwqCOl5+EIPUKXwJqD
DCtHxnWcOCJ+Q/w+qZLjVp1Xx/PntBMRMYSQw2P9YDgP0+Tp7fTrQ8N5uJnbm5yeGjZr2kbZRa1z
jq/7p2n88P2xOF9bm0ZNq9dKRMSNTkLCaze6m/f3Jqenpl0UqN+L/v2fd4/J67n52tpCu1o0rV1D
EZE+FS18hEdkdC0ZBgVqzdFZHJkdc5pSGV2Dri2arHeuVDmH3HSo8lJbWUtIacuz2LOHG1tDdkHo
QZ9V1LYXB3nEJk31nIhsOqcJndVzaxX36Us6LeNj28RBtQZ+U85tUISD5TTFDldT29JaldDXvMlb
SukW7KKqKW33XUt/HDubf2k5V9hK55+z89Eb3i6iddJ0RpE6HAszW0l/WiMQoTWVPqbs+KcaQtqg
Xxv9ESUf7R7b7trslcr41FSuy+59k/33o9oA2iWkILMTQv4/nRsde3YyVQUay1PyR87OAzpC2sCG
vd7zy6sxxpjr5Z1jjjk+2Jg9OyGNQGcnhM5OCDkSP4I0uagCuGCcAAAAAElFTkSuQmCC
"""

class CreateToolTip():
    """
    create a tooltip for a given widget
    """
    def __init__(self, widget, text='widget info'):
        self.waittime = 1000     #miliseconds
        self.wraplength = 180   #pixels
        self.widget = widget
        self.text = text
        self.widget.bind("<Enter>", self.enter)
        self.widget.bind("<Leave>", self.leave)
        self.widget.bind("<ButtonPress>", self.leave)
        self.af_id = None
        self.top_widg = None
        self.popup_list = []

    def __del__(self):
        print("Pop up deleted")

    def enter(self, event=None):
        """ executed when mouse enters widget """
        # pylint: disable=W0613
        self.schedule()

    def leave(self, event=None):
        """ executed when mouse leaves widget """
        # pylint: disable=W0613
        self.unschedule()
        self.hidetip()

    def schedule(self):
        """ called by routine that is triggered when mouse enters widget"""
        self.unschedule()
        self.af_id = self.widget.after(self.waittime, self.showtip)

    def unschedule(self):
        """ cancels the "after" task """
        af_id = self.af_id
        self.af_id = None
        if af_id:
            self.widget.after_cancel(af_id)

    def showtip(self, event=None):
        """ shows the tool tip """
        # pylint: disable=W0613
        poi_x = self.widget.winfo_pointerx() + 10
        poi_y = self.widget.winfo_pointery() + 10
        # creates a toplevel window
        self.top_widg = tkinter.Toplevel(self.widget)
        self.popup_list.append(self.top_widg)
        # Leaves only the label and removes the app window
        self.top_widg.wm_overrideredirect(True)
        self.top_widg.wm_geometry("+%d+%d" % (poi_x, poi_y))
        label = tkinter.Label(self.top_widg, text=self.text, justify='left', \
            background="#ffffff", relief='solid', borderwidth=1, \
            wraplength=self.wraplength)
        label.pack(ipadx=1)

    def hidetip(self):
        """ hides the tooltip and destroys the window when done with it """
        while len(self.popup_list) > 0:
            tw = self.popup_list.pop()
            if tw:
                tw.destroy()
        self.top_widge=None

        #top_widg = self.top_widg
        #self.top_widg = None
        #if top_widg:
        #    top_widg.destroy()


# Node class for linked lists
class Node:
    """ Just a node for a linked list """
    # pylint: disable=R0903
    # Function to initialise the node object
    def __init__(self, data):
        self.data = data  # Assign data
        self.next = None  # Initialize next as null

class CONFIG():
    """ Program Config "Object" and routine ... makes config file and a class to store config
        like baud, port, etc. """
    def __init__(self):
        self.widges = {}
        self.opts = {}
        self.config_value = {}
        self.force_reconfig = False

        self.config_value['baud'] = ''
        self.config_value['serport'] = ''
        self.config_value['rig_id'] = '94'
        self.config_value['ctl_id'] = 'E0'
        self.config_value['geom'] = ''
        self.config_value['scopegeom'] = ''
        self.config_value['after_echo'] = 'On'
        self.config_value['after_transceive'] = 'Off'
        self.config_value['cpu_mode'] = 'Fast'
        self.config_value['theme'] = 'Heathkit'
        self.config_value['loggerport'] = '7524'
        self.config_value['qsyport'] = '7523'
        self.config_filename = str(os.path.expanduser("~"))+"/.PyCOM-7300.config"
        self.widges = {}
        self.opts = {}

    def write_cfg(self):
        """ write out config file """
        # pylint: disable=W0703
        print('opening '+self.config_filename+' for write')
        file_han = open(self.config_filename, 'w+')
        file_han.write('rig_id = '+str(self.config_value['rig_id'])+"\n")
        file_han.write('ctl_id = '+str(self.config_value['ctl_id'])+"\n")
        file_han.write('serport = '+str(self.config_value['serport'])+"\n")
        file_han.write('baud = '+str(self.config_value['baud'])+"\n")
        file_han.write('after_echo = '+str(self.config_value['after_echo'])+"\n")
        file_han.write('after_transceive = '+str(self.config_value['after_transceive'])+"\n")
        file_han.write('cpu_mode = '+str(self.config_value['cpu_mode'])+"\n")
        file_han.write('theme = '+str(self.config_value['theme'])+"\n")
        file_han.write('loggerport = '+str(self.config_value['loggerport'])+"\n")
        file_han.write('qsyport = '+str(self.config_value['qsyport'])+"\n")
        try:
            root.focus()
            s_x = root.geometry().replace('+', ' ').split()[1]
            s_y = root.geometry().replace('+', ' ').split()[2]
            file_han.write('geom = +'+s_x+"+"+s_y+"\n")
        except NameError:
            print("Skipping geometry save first time...")
        try:
            ICOM.scopewin.deiconify()
            sc_x = ICOM.scopewin.geometry().replace('+', ' ').split()[1]
            sc_y = ICOM.scopewin.geometry().replace('+', ' ').split()[2]
            file_han.write('scopegeom = +'+sc_x+"+"+sc_y+"\n")
        except NameError:
            print("Skipping geometry save first time...")
        print("Saved config to "+self.config_filename)
        file_han.close()
        if self.force_reconfig:
            restart_prog()


    def stuffit(self):
        """ assign config vars from widgets in config dialog """
        backup = self.widges['w_backup'].get()
        self.config_value['serport'] = self.widges['w_serport'].get()
        self.config_value['baud'] = self.widges['w_baud'].get()
        self.config_value['rig_id'] = self.widges['w_rig_id'].get()
        self.config_value['ctl_id'] = self.widges['w_ctl_id'].get()
        self.config_value['after_echo'] = self.widges['w_after_echo'].get()
        self.config_value['after_transceive'] = self.widges['w_after_transceive'].get()
        self.config_value['cpu_mode'] = self.widges['w_cpu_mode'].get()
        self.config_value['theme'] = self.widges['w_theme'].get()
        self.config_value['loggerport'] = self.widges['w_loggerport'].get()
        self.config_value['qsyport'] = self.widges['w_qsyport'].get()

        # two "if" so pylint doesn't whine
        for varx in self.config_value:
            if self.config_value[varx] == '' and varx != 'geom' and varx != 'scopegeom':
                print("empty val is "+str(varx))
                return None

        if backup != 'Yes':
            tkinter.messagebox.showerror(
                title="Problem",
                message="You must back up your radio to SD card to run the program.")
            return None

        self.widges['config_win'].destroy()
        self.write_cfg()
        return None

    def kill(self, *args):
        # pylint: disable=W0613
        """ kill the config window and exit the program """
        self.widges['config_win'].destroy()
        sys.exit()

    def build_widges(self):
        """ build the window for the config """
        self.widges['config_win'] = tkinter.Tk()
        self.widges['config_win'].title('Configuration')

        helptext = """You should make a backup of \
your radio to a memory card in the SD slot of your
Icom IC-7300 before using this program.  Consult the user manual for how to
do this.  Author is not liable for anything that happens to your radio from
use of this program.

Serial port must be correct.  You must have permission to read and write from
the port.  On Linux, being a member of the "dialout" group may be what gives
you this.  Or, as root, chmod 666 (port) e.g. /dev/ttyS0 or whatever.  If you
absolutely know you have the port chosen correctly and baud rate right, then
permissions may be what's hanging you up.

On the radio, these are recommended.  YOU BACKED UP TO SD-CARD, RIGHT?

Set > Connectors > CI-V > Address: 94h
Set > Connectors > CI-V > Transceive: OFF
Set > Connectors > CI-V > CI-V Output (for ANT): OFF
Set > Connectors > CI-V > CI-V USB Port: Unlink from Remote
Set > Connectors > CI-V > CI-V USB Baud Rate: 115200
Set > Connectors > CI-V > CI-V USB Echo Back: OFF
Set > Connectors > USB Serial Function: CI-V
Set > Connectors > USB SEND/KEYING > USB Send: OFF
Set > Connectors > USB SEND/KEYING > USB Keying (CW): OFF
Set > Connectors > USB SEND/KEYING > USB Keying (RTTY): OFF

If you goof and choose something incorrectly, you can delete the
.PyCOM-7300.config file from your home folder.  Rememer it starts with a period
so it might be a "hidden" file on your system.

The program may complain about missing modules when you start it up.  Check
your Python-3 documentation for installation of those.  Usually it will be
one of these:

pip3 install pyserial
or
pip install pyserial
or
python3 -m pip install pyserial

Good luck and have fun!

        """
        self.widges['hep_tex'] = tkinter.Text(
            self.widges['config_win'], height=30, width=80)
        self.widges['skrolly'] = tkinter.Scrollbar(
            self.widges['config_win'], command=self.widges['hep_tex'].yview)
        self.widges['hep_tex'].insert(tkinter.END, helptext)
        self.widges['hep_tex']['yscrollcommand'] = self.widges['skrolly'].set
        self.widges['hep_tex'].configure(state='disabled')
        self.widges['config_win'].bind("<Escape>", self.kill)
        self.widges['config_win'].bind("<Control-w>", self.kill)

        self.widges['l_serport'] = tkinter.ttk.Label(
            self.widges['config_win'], text="Port:")
        self.widges['l_baud'] = tkinter.ttk.Label(
            self.widges['config_win'], text="Baud:")
        self.widges['l_rig_id'] = tkinter.ttk.Label(
            self.widges['config_win'], text="Rig ID:")
        self.widges['l_ctl_id'] = tkinter.ttk.Label(
            self.widges['config_win'], text="Controller ID:")
        self.widges['l_backup'] = tkinter.ttk.Label(
            self.widges['config_win'], text="I have made a backup:")
        self.widges['l_after_echo'] = tkinter.ttk.Label(
            self.widges['config_win'], text="On quit, set CI-V echo:")
        self.widges['l_after_transceive'] = tkinter.ttk.Label(
            self.widges['config_win'], text="On quit, set CI-V transceive:")
        self.widges['l_cpu_mode'] = tkinter.ttk.Label(
            self.widges['config_win'], text="CPU Mode:")
        self.widges['l_theme'] = tkinter.ttk.Label(
            self.widges['config_win'], text="Color Theme:")
        self.widges['l_loggerport'] = tkinter.ttk.Label(
            self.widges['config_win'], text="Logger CI-V TCP Port (NON N3FJP API!):")
        self.widges['l_qsyport'] = tkinter.ttk.Label(
            self.widges['config_win'], text="Skimmer QSY Request TCP Port:")

        self.widges['butt_frame'] = tkinter.ttk.Frame(
            self.widges['config_win'])
        self.widges['b_save'] = tkinter.ttk.Button(
            self.widges['butt_frame'], text="Save", command=self.stuffit)
        self.widges['b_cancel'] = tkinter.ttk.Button(
            self.widges['butt_frame'], text="Cancel", command=sys.exit)

        self.widges['w_serport'] = tkinter.ttk.Combobox(
            self.widges['config_win'], values=self.opts['port_devs'])
        self.widges['w_baud'] = tkinter.ttk.Combobox(
            self.widges['config_win'], values=self.opts['baud_rates'])
        self.widges['w_rig_id'] = tkinter.ttk.Entry(
            self.widges['config_win'], text='94')
        self.widges['w_ctl_id'] = tkinter.ttk.Entry(
            self.widges['config_win'], text='E0')
        self.widges['w_backup'] = tkinter.ttk.Combobox(
            self.widges['config_win'], values=self.opts['ny'])
        self.widges['w_after_echo'] = tkinter.ttk.Combobox(
            self.widges['config_win'], values=self.opts['ooa'])
        self.widges['w_after_transceive'] = tkinter.ttk.Combobox(
            self.widges['config_win'], values=self.opts['oob'])
        self.widges['w_cpu_mode'] = tkinter.ttk.Combobox(
            self.widges['config_win'], values=self.opts['cpm'])
        self.widges['w_theme'] = tkinter.ttk.Combobox(
            self.widges['config_win'], values=self.opts['thm'])
        self.widges['w_loggerport'] = tkinter.ttk.Entry(
            self.widges['config_win'], text='7301')
        self.widges['w_qsyport'] = tkinter.ttk.Entry(
            self.widges['config_win'], text='7374')

    def populate_widges(self):
        """ put stuff in widges """
        self.widges['w_rig_id'].delete(0, tkinter.END)
        self.widges['w_ctl_id'].delete(0, tkinter.END)
        self.widges['w_serport'].delete(0, tkinter.END)
        self.widges['w_baud'].delete(0, tkinter.END)
        self.widges['w_after_echo'].delete(0, tkinter.END)
        self.widges['w_after_transceive'].delete(0, tkinter.END)
        self.widges['w_cpu_mode'].delete(0, tkinter.END)
        self.widges['w_theme'].delete(0, tkinter.END)
        self.widges['w_loggerport'].delete(0, tkinter.END)
        self.widges['w_qsyport'].delete(0, tkinter.END)

        self.widges['w_rig_id'].insert(0, self.config_value['rig_id'])
        self.widges['w_ctl_id'].insert(0, self.config_value['ctl_id'])
        self.widges['w_serport'].insert(0, self.config_value['serport'])
        self.widges['w_baud'].insert(0, self.config_value['baud'])
        self.widges['w_after_echo'].insert(0, self.config_value['after_echo'])
        self.widges['w_after_transceive'].insert(0, self.config_value['after_transceive'])
        self.widges['w_cpu_mode'].insert(0, self.config_value['cpu_mode'])
        self.widges['w_theme'].insert(0, self.config_value['theme'])
        self.widges['w_loggerport'].insert(0, self.config_value['loggerport'])
        self.widges['w_qsyport'].insert(0, self.config_value['qsyport'])

    def layout_widges(self):
        """ arrange widges """
        cur_row = 1

        self.widges['hep_tex'].grid(row=cur_row, column=1, columnspan=2)
        self.widges['skrolly'].grid(row=cur_row, column=3, sticky='NS')

        cur_row = cur_row+1
        self.widges['l_serport'].grid(row=cur_row, column=1, sticky='E')
        self.widges['w_serport'].grid(row=cur_row, column=2, sticky='W')

        cur_row = cur_row+1
        self.widges['l_baud'].grid(row=cur_row, column=1, sticky='E')
        self.widges['w_baud'].grid(row=cur_row, column=2, sticky='W')

        cur_row = cur_row+1
        self.widges['l_rig_id'].grid(row=cur_row, column=1, sticky='E')
        self.widges['w_rig_id'].grid(row=cur_row, column=2, sticky='W')

        cur_row = cur_row+1
        self.widges['l_ctl_id'].grid(row=cur_row, column=1, sticky='E')
        self.widges['w_ctl_id'].grid(row=cur_row, column=2, sticky='W')

        cur_row = cur_row+1
        self.widges['l_after_echo'].grid(row=cur_row, column=1, sticky='E')
        self.widges['w_after_echo'].grid(row=cur_row, column=2, sticky='W')

        cur_row = cur_row+1
        self.widges['l_after_transceive'].grid(row=cur_row, column=1, sticky='E')
        self.widges['w_after_transceive'].grid(row=cur_row, column=2, sticky='W')

        cur_row = cur_row+1
        self.widges['l_cpu_mode'].grid(row=cur_row, column=1, sticky='E')
        self.widges['w_cpu_mode'].grid(row=cur_row, column=2, sticky='W')

        cur_row = cur_row+1
        self.widges['l_theme'].grid(row=cur_row, column=1, sticky='E')
        self.widges['w_theme'].grid(row=cur_row, column=2, sticky='W')

        cur_row = cur_row+1
        self.widges['l_loggerport'].grid(row=cur_row, column=1, sticky='E')
        self.widges['w_loggerport'].grid(row=cur_row, column=2, sticky='W')

        cur_row = cur_row+1
        self.widges['l_qsyport'].grid(row=cur_row, column=1, sticky='E')
        self.widges['w_qsyport'].grid(row=cur_row, column=2, sticky='W')

        cur_row = cur_row+1
        self.widges['l_backup'].grid(row=cur_row, column=1, sticky='E')
        self.widges['w_backup'].grid(row=cur_row, column=2, sticky='W')

        cur_row = cur_row+1
        self.widges['b_save'].grid(row=1, column=1)
        self.widges['b_cancel'].grid(row=1, column=2)
        self.widges['butt_frame'].grid(row=cur_row, column=1, columnspan=2)

        self.widges['config_win'].update()

    def read_cfg(self):
        """ if config file exists, read it in """
        if os.path.exists(self.config_filename):
            file_han = open(self.config_filename, 'r')
            cfglines = file_han.readlines()
            file_han.close()
            for cfgline in cfglines:
                items = cfgline.split('=')
                self.config_value[items[0].strip()] = items[1].strip()
        else:
            print("no config file "+self.config_filename)

        needs_reconfig = False

        for varx in self.config_value:
            if varx in ('scopegeom','geom'):
                continue
            if self.config_value[varx] == '':
                print("config value "+varx+" missing")
                needs_reconfig = True

        if self.force_reconfig:
            print("Forced reconfig...")
            needs_reconfig = True

        if (not os.path.exists(self.config_filename) or needs_reconfig):
            self.opts['ports'] = serial.tools.list_ports.comports()
            if not self.opts['ports']:
                print("No serial ports present.  If using USB, be sure radio" + \
                        " is plugged in and device driver is present.")
                sys.exit()
            self.opts['port_devs'] = []
            self.opts['baud_rates'] = []
            self.opts['ny'] = ['No', 'Yes']
            self.opts['ooa'] = ['On', 'Off']
            self.opts['oob'] = ['Off', 'On']
            self.opts['cpm'] = ['Moderate', 'Fast', 'CPU Saver']
            self.opts['thm'] = ['Medium', 'Light', 'Heathkit',
                                'Kenwood', 'HotDog Stand', 'Go Big Blue']

            for p_d in self.opts['ports']:
                self.opts['port_devs'].append(p_d.device)

            for b_r in serial.Serial.BAUDRATES[::-1]:
                if b_r <= 200000:
                    self.opts['baud_rates'].append(b_r)

            self.build_widges()
            self.populate_widges()

            if self.config_value['rig_id'] == '':
                print('hard coding 94 because empty');
                self.widges['w_rig_id'].insert(0, '94')
            if self.config_value['ctl_id'] == '':
                print('hard coding E0 because empty');
                self.widges['w_ctl_id'].insert(0, 'E0')


            self.layout_widges()

            self.widges['config_win'].mainloop()


class fakequeue():

    def __init__(self):
        self.stack = list()
        
    def qsize(self):
        return len(self.stack)

    def empty(self):
        return self.qsize() == 0

    def put(self,data,blocky=False):
        self.stack.append(data)

    def putfront(self,data,blocky=False):
        self.stack.insert(0,data)

    def get(self,blocky=False):
        if self.empty():
            return None
        return self.stack.pop(0)



class COMM():
    """ handle queueing of serial port data """
    # pylint: disable=R0902
    def __init__(self):


        self.buf=bytes()
        self.recvq = fakequeue()
        self.quitq = fakequeue()
        self.pauseq = fakequeue()

        self.send_preamble_bin = b'\xfe\xfe'+bytes.fromhex(config.config_value['rig_id'])+\
                bytes.fromhex(config.config_value['ctl_id'])
        self.recv_preamble_bin = b'\xfe\xfe'+bytes.fromhex(config.config_value['ctl_id'])+\
                bytes.fromhex(config.config_value['rig_id'])

        self.suffix_bin = b'\xfd'

        if os.name == 'nt':
            self.ser=serial.Serial(config.config_value['serport'], \
                                   baudrate=config.config_value['baud'], \
                                   bytesize=serial.EIGHTBITS, \
                                   parity=serial.PARITY_NONE, \
                                   stopbits=serial.STOPBITS_ONE, \
                                   rtscts=True, \
                                   dsrdtr=False, \
                                   xonxoff=False, \
                                   timeout=.1) 

            
        
        if os.name == 'posix':
            # iflag, oflag, cflag, lflag, ispeed, ospeed, [cc]
            self.tcsetattrlist = [
                0, 0, 0, 0, 0, 0, 
                [   b'\x00', b'\x00', b'\x00', b'\x00', b'\x00', 
                    0, 0, 
                    b'\x00', b'\x00', b'\x00', b'\x00', b'\x00', 
                    b'\x00', b'\x00', b'\x00', b'\x00', b'\x00', 
                    b'\x00', b'\x00', b'\x00', b'\x00', b'\x00', 
                    b'\x00', b'\x00', b'\x00', b'\x00', b'\x00', 
                    b'\x00', b'\x00', b'\x00', b'\x00', b'\x00']]

            if hasattr(termios, 'TIOCINQ'):
                self.TIOCINQ = termios.TIOCINQ
            else:
                self.TIOCINQ = getattr(termios, 'FIONREAD', 0x541B)
            self.TIOCOUTQ = getattr(termios, 'TIOCOUTQ', 0x5411)
            self.TIOCM_zero_str = struct.pack('I', 0)

            self.ser = os.open( config.config_value['serport'], os.O_RDWR)

            self.oldattr=termios.tcgetattr(self.ser)
            self.blankattr = termios.tcsetattr(self.ser,termios.TCSANOW,self.tcsetattrlist)
            self.blankattr=termios.tcgetattr(self.ser)
            self.newattr=self.blankattr

            # 2 is c, 4 is in, 5 is out
            self.newattr[2] &= ~termios.CSIZE  # turn OFF the CSIZE bit
            self.newattr[2] |= termios.CS8     # turn ON the CS8 bit
            self.newattr[4] = self.newattr[5] = getattr(termios,'B{}'.format(config.config_value['baud']) ) # 4 and 5 are baud speed
            self.newattr[6][termios.VMIN] = 1   # big array of values, position VMIN = 1
            self.newattr[6][termios.VTIME] = 0  # big array of values, position VTIME = 1
            termios.tcsetattr(self.ser,termios.TCSANOW,self.newattr)

    def in_waiting(self):
        """Return the number of bytes currently in the input buffer."""
        #~ s = fcntl.ioctl(eelf.fd, termios.FIONREAD, TIOCM_zero_str)
        s = fcntl.ioctl(self.ser, self.TIOCINQ, self.TIOCM_zero_str)
        return struct.unpack('I', s)[0]

    def read_until(self,expected=b'\x10'):
        """\
        Read until an expected sequence is found ('\n' by default), the size
        is exceeded or until timeout occurs.
        """
        # only read all stuff off serial port if the look-for isn't in the 
        # buffer already, and append it to buf
        if expected not in self.buf:
            iw=self.in_waiting()
            if iw > 0:
                self.buf += bytes(os.read(self.ser,iw))

        # don't do "else" here because you want to test again
        if expected in self.buf:
            lenterm = len(expected)
            self.retbuf = self.buf[0:self.buf.index(expected)+lenterm]
            self.buf=self.buf[self.buf.index(expected)+lenterm:]
            return bytearray(self.retbuf)
        else:
            return bytearray()

    if os.name == 'posix':      


            def no_buf_read_until(self,self_fh, expected=b'\x10'):
                    """\
                    Read until an expected sequence is found ('\n' by default), the size
                    is exceeded or until timeout occurs.
                    """
                    lenterm = len(expected)
                    line = bytearray()
                    #timeout = Timeout(self._timeout)
                    while True:
                        #c = self_fh.read(1)
                        c = os.read(self_fh,1)
                        if c:
                            line += c
                            if line[-lenterm:] == expected:
                                break
                        else:
                            break
                    return bytes(line)

            def no_buf_direct_receive(self):
                #count=0
                #while self.in_waiting() > 0 and count < 3:
                #while self.in_waiting() > 0 and count < 3:
                if self.in_waiting() > 0 and self.pauseq.qsize() == 0:
                    # note self.read_until vs. self.ser.read_until for win
                    self.no_buf_read_until(self.ser,self.recv_preamble_bin)
                    rxbytes = self.recv_preamble_bin+self.no_buf_read_until(self.ser,self.suffix_bin)
                    if rxbytes != self.recv_preamble_bin:
                        return rxbytes
                #    count+=1


            def send_direct(self,s_q):
                if s_q is not None:
                    os.write(self.ser,s_q)
                    time.sleep(.0040)

            def direct_receive(self):
                #count=0
                #while self.in_waiting() > 0 and count < 3:
                #while self.in_waiting() > 0 and count < 3:
                if self.in_waiting() > 0 and self.pauseq.qsize() == 0:
                    # note self.read_until vs. self.ser.read_until for win
                    self.read_until(self.recv_preamble_bin)
                    rxbytes = self.recv_preamble_bin+self.read_until(self.suffix_bin)
                    #print("rxbytes is "+str(rxbytes))
                    if rxbytes != self.recv_preamble_bin:
                        self.recvq.put(rxbytes, True)
                #    count+=1

    if os.name == 'nt':
            def send_direct(self,s_q):
                if s_q is not None:
                    self.ser.write(s_q)
                    self.ser.flush()
                    time.sleep(.0040)

            def direct_receive(self):
                if self.ser.in_waiting > 0:
                    # note self.read_until vs. self.ser.read_until for win
                    self.ser.read_until(self.recv_preamble_bin)
                    rxbytes = self.recv_preamble_bin+self.ser.read_until(self.suffix_bin)
                    if rxbytes != self.recv_preamble_bin:
                        self.recvq.put(rxbytes, True)
                    

                    
    def send_direct_command(self, cmdkey):
        """ add to send queue by command name e.g. this_vfo_freq """
        self.send_direct(self.send_preamble_bin
                               + ICOM.binary_send_item[cmdkey]
                               + self.suffix_bin)


#class LabelProgressbar(tkinter.ttk.Progressbar):
#    """ Progress Bar with label that acts like progress bar such that options work """
#    # pylint: disable=R0901
#    def __init__(self, parent, labeltext, **options):
#        w_frame = tkinter.Frame(parent)
#        tkinter.ttk.Progressbar.__init__(self, w_frame, **options)
#        self._label = tkinter.Label(w_frame, text=labeltext)
#        self._label.grid(row=1, column=1)
#        self.grid(row=1, column=2,sticky='N')
#        self.grid = w_frame.grid
#        self.grid_remove = w_frame.grid_remove

class LabelEntry(tkinter.Entry):
    """ Entry with label that acts like Entry such that options work """
    # pylint: disable=R0901
    def __init__(self, parent, labeltext, **options):
        w_frame = tkinter.Frame(parent)
        tkinter.Entry.__init__(self, w_frame, **options)
        self._label = tkinter.Label(w_frame, text=labeltext)
        self._label.grid(row=1, column=1)
        self.grid(row=1, column=2)
        self.grid = w_frame.grid
        self.grid_remove = w_frame.grid_remove

class LabelListbox(tkinter.Listbox):
    """ Listbox with label that acts like listbox such that options work """
    # pylint: disable=R0901
    def __init__(self, parent, labeltext, **options):
        w_frame = tkinter.Frame(parent)
        tkinter.Listbox.__init__(self, w_frame, **options)
        self._label = tkinter.Label(w_frame, text=labeltext)
        self._label.grid(row=1, column=1)
        self.grid(row=1, column=2)
        self.grid = w_frame.grid
        self.grid_remove = w_frame.grid_remove

class LabelCombobox(tkinter.ttk.Combobox):
    """ Combobox with label that acts like combobox such that options work """
    # pylint: disable=R0901
    def __init__(self, parent, labeltext, **options):
        w_frame = tkinter.Frame(parent)
        tkinter.ttk.Combobox.__init__(self, w_frame, **options)
        self._label = tkinter.Label(w_frame, text=labeltext)
        self._label.grid(row=1, column=1)
        self.grid(row=1, column=2)
        self.grid = w_frame.grid
        self.grid_remove = w_frame.grid_remove

class FlatScale(tkinter.Scale):
    """ scale with label on the side instead of on top like a chump """
    # pylint: disable=R0901
    def __init__(self, parent, labeltext, numwidth, **options):
        w_frame = tkinter.Frame(parent)
        tkinter.Scale.__init__(self, w_frame, **options)

        self._label = tkinter.Label(w_frame, text=labeltext)
        self._vallb = tkinter.Label(w_frame, textvariable=self['variable'], width=numwidth)

        self._label.grid(row=1, column=1)
        self.grid(row=1, column=2)
        self._vallb.grid(row=1, column=3)

        self.grid = w_frame.grid
        self.grid_remove = w_frame.grid_remove

def reverse_hex_to_bcd(hexx):
    """ convert e.g. 012345 to 452301 """
    bcdstr = ""
    for h_pair in reversed(textwrap.wrap(hexx, 2)):
        bcdstr = bcdstr+h_pair
    return bcdstr

def keyercononly(val):
    """ validation routine max 69 char CW keyer chars with asterisk """
    if len(val) > 69:
        return False
    for k_ch in val.upper():
        if not k_ch in '*0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ/?.-, :\'() = +"@ ^':
            return False
    return True

def keyeronly(val):
    """ validation routine max 69 char CW keyer chars """
    if len(val) > 70:
        return False
    for k_ch in val.upper():
        if not k_ch in '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ/?.-, :\'() = +"@ ^':
            return False
    return True

def cwonly(val): # used to allow only cw chars
    """ validation routine CW keyer chars """
    for k_ch in val.upper():
        if not k_ch in '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ/?.-, :\'() = +"@ ^':
            return False
    return True

def numonly(val): # used to allow only numbers and periods in input fields (VFOs)
    """ validation routine num and radix only"""
    for k_ch in val:
        if not k_ch in {'1', '2', '3', '4', '5', '6', '7', '8', '9', '0', '.'}:
            return False
    return True

class RadioMemory:
    """ icom 7300 radio memory struct thing """
    # pylint: disable=R0902
    # pylint: disable=R0903
    # pylint: disable=R0915
    def __init__(self, ret):

        if ret == 'ff':
            self.set = False
        else:
            self.set = True

            #self.bin = ret
            self.hex = ret

            self.vfoformat = "{:>11s}|{:>6s}|{:>4s}|{:>3s}|{:>4s}|{:>6s}|{:>6s}"
            self.memchformat = "{:>8s}|{:>2s}|"+self.vfoformat+"|"+self.vfoformat+"|{:<11s}"
            self.split_values = collections.OrderedDict([('0', 'SIMPLEX'), ('1', 'SPLIT')])
            self.operating_mode_values = collections.OrderedDict([
                ('00', 'LSB'),
                ('01', 'USB'),
                ('02', 'AM'),
                ('03', 'CW'),
                ('04', 'RTTY'),
                ('05', 'FM'),
                ('06', 'N/A'),
                ('07', 'CW-R'),
                ('08', 'RTTY-R')
                ])
            self.filter_values = collections.OrderedDict([
                ('01', 'FIL1'),
                ('02', 'FIL2'),
                ('03', 'FIL3')
                ])
            self.data_mode_values = collections.OrderedDict([
                ('0', 'OFF'),
                ('1', 'ON')
                ])
            self.tone_type_values = collections.OrderedDict([
                ('0', 'OFF'),
                ('1', 'TONE'),
                ('2', 'TSQL')
                ])
            self.minimemchformat = "{:>11s} {:>6s} {:<11s}"


            self.modified = False

            self.splitraw = self.hex[0]
            self.selectmemraw = self.hex[1]

            self.rx_frequency_raw = self.hex[2:12]
            self.rx_mode_raw = self.hex[12:14]
            self.rx_filter_raw = self.hex[14:16]
            self.rx_data_raw = self.hex[16:17]
            self.rx_tone_raw = self.hex[17:18]
            self.rx_repeatertone_raw = self.hex[18:24]
            self.rx_repeatertsql_raw = self.hex[24:30]

            self.tx_frequency_raw = self.hex[30:40]
            self.tx_mode_raw = self.hex[40:42]
            self.tx_filter_raw = self.hex[42:44]
            self.tx_data_raw = self.hex[44:45]
            self.tx_tone_raw = self.hex[45:46]
            self.tx_repeatertone_raw = self.hex[46:52]
            self.tx_repeatertsql_raw = self.hex[52:58]

            self.nameraw = bytes.fromhex(self.hex)[29:39]

            self.split = self.split_values[self.splitraw]
            self.selectmem = '*'+self.selectmemraw
            self.rx_frequency_hz = "{:}".format(int(reverse_hex_to_bcd(self.rx_frequency_raw)))
            self.rx_frequency_khz = "{:.3f}".format(float(self.rx_frequency_hz)/1000)
            self.rx_frequency_mhz = "{:.6f}".format(float(self.rx_frequency_hz)/1000000)
            self.rx_frequency_vfo = "{:,}".format(int(self.rx_frequency_hz)).replace(', ', '.')
            self.rx_mode = self.operating_mode_values[self.rx_mode_raw]
            self.rx_filter = self.filter_values[self.rx_filter_raw]
            self.rx_data = self.data_mode_values[self.rx_data_raw]
            self.rx_tone = self.tone_type_values[self.rx_tone_raw]
            self.rx_repeatertone_hz = "{:.2f}".format(float(int(self.rx_repeatertone_raw)/10))
            self.rx_repeatertsql_hz = "{:.2f}".format(float(int(self.rx_repeatertsql_raw)/10))

            self.tx_frequency_hz = "{:}".format(int(reverse_hex_to_bcd(self.tx_frequency_raw)))
            self.tx_frequency_khz = "{:.3f}".format(float(self.tx_frequency_hz)/1000)
            self.tx_frequency_mhz = "{:.6f}".format(float(self.tx_frequency_hz)/1000000)
            self.tx_frequency_vfo = "{:,}".format(int(self.tx_frequency_hz)).replace(', ', '.')
            self.tx_mode = self.operating_mode_values[self.tx_mode_raw]
            self.tx_filter = self.filter_values[self.tx_filter_raw]
            self.tx_data = self.data_mode_values[self.tx_data_raw]
            self.tx_tone = self.tone_type_values[self.tx_tone_raw]
            self.tx_repeatertone_hz = "{:.2f}".format(float(int(self.tx_repeatertone_raw)/10))
            self.tx_repeatertsql_hz = "{:.2f}".format(float(int(self.tx_repeatertsql_raw)/10))

class IC7300:
    """ big overly complex class for rig """
    # pylint: disable=R0902
    # pylint: disable=R0915
    def __init__(self):

        self.pwrtbl=[]
        self.pwrtbl.append([0, 0.0])
        self.pwrtbl.append([21, 5.0])
        self.pwrtbl.append([43, 10.0])
        self.pwrtbl.append([65, 15.0])
        self.pwrtbl.append([83, 20.0])
        self.pwrtbl.append([95, 25.0])
        self.pwrtbl.append([105, 30.0])
        self.pwrtbl.append([114, 35.0])
        self.pwrtbl.append([124, 40.0])
        self.pwrtbl.append([143, 50.0])
        self.pwrtbl.append([183, 75.0])
        self.pwrtbl.append([213, 100.0])
        self.pwrtbl.append([255, 120.0])
    
        self.swrtbl=[]
        self.swrtbl.append([0, 0.0])
        self.swrtbl.append([48, 12.5])
        self.swrtbl.append([80, 27.0])
        self.swrtbl.append([103, 40.0])
        self.swrtbl.append([120, 50.0])
        self.swrtbl.append([255, 100.0])

        self.operating_mode_values = collections.OrderedDict([
            ('00', 'LSB'),
            ('01', 'USB'),
            ('02', 'AM'),
            ('03', 'CW'),
            ('04', 'RTTY'),
            ('05', 'FM'),
            ('06', 'N/A'),
            ('07', 'CW-R'),
            ('08', 'RTTY-R')
            ])

        #        self.comp_levels = (11, 34, 58, 81, 104, 128, 151, 174, 197, 221, 244)
        # 41 of these, 0 to 41
        # LSB USB CW CW-R

        # It will look and see if it's in a band plan mode, and if not
        # change it.  Bands whose entire spectrum is phone have both.

        # switch to "AM" if not in any of these if auto mode is on

        self.bandplan = {}
        for x in (160,80,60,40,30,20,17,15,12,10,6):
            self.bandplan[x]={}

        self.bandplan[160]['CW']  = (1800000,  2000000)
        self.bandplan[160]['LSB'] = (1800000,  2000000)

        self.bandplan[80]['CW']   = (3500000,  3600000)
        self.bandplan[80]['LSB']  = (3600000,  4000000)

        self.bandplan[60]['CW']   = (5330000,  5405000)
        self.bandplan[60]['USB']  = (5330000,  5405000)

        self.bandplan[40]['CW']   = (7000000,  7125000)
        self.bandplan[40]['LSB']  = (7125000,  7300000)

        self.bandplan[30]['CW']   = (10100000,10150000)

        self.bandplan[20]['CW']   = (14000000,14150000)
        self.bandplan[20]['USB']  = (14150000,14350000)

        self.bandplan[17]['CW']   = (18068000,18110000)
        self.bandplan[17]['USB']  = (18110000,18168000)

        self.bandplan[15]['CW']   = (21000000,21200000)
        self.bandplan[15]['USB']  = (21200000,21450000)

        self.bandplan[12]['CW']   = (24890000,24930000)
        self.bandplan[12]['USB']  = (24930000,24990000)

        self.bandplan[10]['CW']   = (28000000,28300000)
        self.bandplan[10]['USB']  = (28300000,29700000)

        self.bandplan[6]['CW']    = (50000000,50100000)
        self.bandplan[6]['USB']   = (50100000,54000000)



        self.ekll = {}
        self.ekee = {}
        self.bandwidths = {}
        self.bandwidths['00'] = [ \
        "50", "100", "150", "200", "250", "300", "350", "400", "450", "500", \
        "600", "700", "800", "900", "1000", "1100", "1200", "1300", "1400", "1500", \
        "1600", "1700", "1800", "1900", "2000", "2100", "2200", "2300", "2400", "2500", \
        "2600", "2700", "2800", "2900", "3000", "3100", "3200", "3300", "3400", "3500", \
        "3600"]
        self.bandwidths['01'] = self.bandwidths['00']
        self.bandwidths['03'] = self.bandwidths['00']
        self.bandwidths['07'] = self.bandwidths['00']

        # 32 of these, 0 to 31 IDENTICAL TO CW/SSB UP TO 2700 THEN STOPS
        # RTTY RTTY-R
        self.bandwidths['04'] = [ \
        "50", "100", "150", "200", "250", "300", "350", "400", "450", "500", \
        "600", "700", "800", "900", "1000", "1100", "1200", "1300", "1400", "1500", \
        "1600", "1700", "1800", "1900", "2000", "2100", "2200", "2300", "2400", "2500", \
        "2600", "2700"]
        self.bandwidths['08'] = self.bandwidths['04']

        # AM
        self.bandwidths['02'] = [ \
        "200", "400", "600", "800", "1000", "1200", "1400", "1600", "1800", "2000", \
        "2200", "2400", "2600", "2800", "3000", "3200", "3400", "3600", "3800", "4000", \
        "4200", "4400", "4600", "4800", "5000", "5200", "5400", "5600", "5800", "6000", \
        "6200", "6400", "6600", "6800", "7000", "7300", "7400", "7300", "7800", "8000", \
        "8200", "8400", "8600", "8800", "9000", "9200", "9400", "9600", "9800", "10000"]

        # FM
        self.bandwidths['05'] = ["fixed"]

        self.agc = {}
        # FM
        self.agc['05'] = ['n/a']

        # SSB CW RTTY
        self.agc['00'] = [0.0, 0.1, 0.2, 0.3, 0.5, 0.8, 1.2, 1.6, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0]
        self.agc['01'] = self.agc['00']
        self.agc['03'] = self.agc['00']
        self.agc['04'] = self.agc['00']
        self.agc['07'] = self.agc['00']
        self.agc['08'] = self.agc['00']

        # AM
        self.agc['02'] = [0.0, 0.3, 0.5, 0.8, 1.2, 1.6, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]

        self.keyertypes = ['Normal', '190->ANO', '190->ANT', '190->1NO', '190->1NT']

        self.nr_levels = (8, 24, 40, 56, 72, 88, 104, 120, 136, 152, 168, 184, 200, 216, 232, 248)

        self.modes = collections.OrderedDict([
            ("LSB", '00'),
            ("USB", '01'),
            ("AM", '02'),
            ("CW", '03'),
            ("RTTY", '04'),
            ("FM", '05'),
            ("CW-R", '07'),
            ("RTTY-R", '08')
            ]) # used by VFO widg

        self.rig_id_bin = bytes.fromhex(config.config_value['rig_id'])
        self.ctl_id_bin = bytes.fromhex(config.config_value['ctl_id'])
        self.tra_id_bin = bytes.fromhex('00')

        self.powerpfx_bin = b'\xfe'*150
        self.prefix_bin = b'\xfe\xfe'
        self.send_preamble_bin = b'\xfe\xfe'+self.rig_id_bin+self.ctl_id_bin
        self.receive_preamble_bin = b'\xfe\xfe'+self.ctl_id_bin+self.rig_id_bin
        self.transceive_preamble_bin = b'\xfe\xfe'+self.tra_id_bin+self.rig_id_bin
        self.suffix_bin = b'\xfd'
        self.irpl = len(self.receive_preamble_bin)

        # rxhash is a dict of hex pairs that match bytes of command strings, used to
        # trace down to find which command just came back from the receiver, e.g. if '160201'
        # comes back, we look at rxhash['16'] and see if it is a var or another dict.
        # if it's a dict, we go and see if '02' is a var or a dict.  If it's a dict,
        # we look and see that (maybe) '01' is a var.  01 is the value and 1602 is the
        # command - this has to be done due to varying lengths of strings coming back
        # from the radio.  Things that match nothing are ignored
        #

        self.rxhash = {}
        self.binary_send_item = {}
        #self.gui_touched = 0
        #self.button_pressed = False

        self.memory_channel = {}
        self.radio_date = tkinter.StringVar()
        self.radio_time = tkinter.StringVar()
        self.radio_tz = tkinter.StringVar()
        self.my_call_sign = tkinter.StringVar()
        self.status_line = tkinter.StringVar()
        self.overflow_indicator = tkinter.StringVar()
        self.overflow_indicator.set('OVF')


        self.vfo_touched = -99999

        self.do_not_poll_mask = 0

        self.poll_meters_mask = 1     # now
        self.poll_vfos_mask = 2     # now
        self.poll_controls_mask = 4
        self.poll_scope_mask = 8
        self.poll_keyer_mask = 16
        self.poll_mem_mask = 32

        self.poll_all_mask = 255

        # dict of polltype (0, 1, 2, 4, 8, etc) vars below per widget
        self.current_poll_cycle = 0
        self.polling_is_on = True

        self.poll_list = {}
        self.poll_first = {}

        # make the "1" first by hand as it's the "head" of the list.
        self.memory_poll_node = Node(bytes.fromhex(('0000'+str(1))[-4:]))
        # point aa to that
        a_node = self.memory_poll_node
        for i_r in range(2, 100):
            # make new nodes already linked to its previous one
            a_node.next = Node(bytes.fromhex(('0000'+str(i_r))[-4:]))
            # jump to the next one
            a_node = a_node.next
        # after done, point last one to first.
        a_node.next = self.memory_poll_node

        # make the "1" first by hand as it's the "head" of the list.
        self.keyer_poll_node = Node(bytes.fromhex(('00'+str(1))[-2:]))
        # point aa to that
        a_node = self.keyer_poll_node
        for i_r in range(2, 9):
            # make new nodes already linked to its previous one
            a_node.next = Node(bytes.fromhex(('00'+str(i_r))[-2:]))
            # jump to the next one
            a_node = a_node.next
        # after done, point last one to first.
        a_node.next = self.keyer_poll_node

        # dict of poll types by widg
        #self.poll_type = {}
        self.poll_type = collections.OrderedDict()

        # dict of memory keyer contents
        #self.KEYER = {}
        #self.VKEYER = {}
        self.cw_keyer = collections.OrderedDict()
        self.cw_keyer_edit = collections.OrderedDict()
        self.cw_keyer_tip = collections.OrderedDict()
        self.voice_keyer = collections.OrderedDict()

        # list of VFO widgets that is used to test if root.focus() is there
        self.vfo_widget = []

        # dict of the actual widgets
        #self.widget_object = {}
        self.widget_object = collections.OrderedDict()

        self.scope_mult = 1
        self.scopedata = {}
        self.peaks = {}
        self.scope_spectrum_line = {}
        self.scope_peak_line = {}
        self.scope_fill_line = {}
        self.grid_line = {}
        self.prevyaxis = {}
        self.prevpeak = {}
        self.prevline = {}
        for x in range(0,476):
            self.prevyaxis[x]=160
            self.prevpeak[x]=160
            self.prevline[x]=160
        self.wafa_top_tag = '0'
        self.wafa_flip_tag = '0'
        self.wafa_bot = 60

        self.scope_c_or_f = b''
        self.scope_one_freq = b''
        self.scope_two_freq = b''
        self.scope_hzper  = 0
        self.scope_bottom  = 0
        self.scope_color = {}
        self.scope_color['scope_fill_color']='#ffffff'
        self.scope_color['scope_line_color']='#808080'
        self.scope_color['scope_peak_color']='#444444'
        self.rx_color_change = True

        self.yaxcolor={}
        for x in range(0,161):
            self.yaxcolor[x]={0:'black', 32:'#0000FF', 64:'#00ffff', 96:'#00ff00', 128:'#ffff00', 160:'#ff0000'}[((160-x)+31) & (224)]

        self.gui_theme = collections.OrderedDict([
            ('', {}),
            ('Dark', {'background':'#777777', 'foreground':'white'}),
            ('Medium', {'background':'#aaaaaa', 'foreground':'black'}),
            ('Light', {'background':'#dddddd', 'foreground':'black'}),
            ('XHeathkit', {'background':'#63b1a3', 'foreground':'black'}),
            ('YHeathkit', {'background':'#63b1a3', 'foreground':'black'}),
            ('Heathkit', {'background':'#2e6a6b', 'foreground':'black'}),
            ('Yaesu', {'background':'#72736b', 'foreground':'white'}),
            ('Kenwood', {'background':'#ada8a4', 'foreground':'black'}),
            ('Icom', {'background':'#292927', 'foreground':'white'}),
            ('HotDog Stand', {'background':'#ffff00', 'foreground':'black'}),
            ('Go Big Blue', {'background':'blue', 'foreground':'#808080'})
            ])

        # last_polled_value dict is a "mirror" of
        # widget_variable dict so that it can be referenced despite widgvar
        # being updated by a slider or control
        #self.widget_variable = {}
        #self.last_polled_value = {}
        self.widget_variable = collections.OrderedDict()
        self.last_polled_value = collections.OrderedDict()

        #self.frames = {}
        self.frames = collections.OrderedDict()
        if config.config_value['baud'] == '115200':
            self.scopewin = tkinter.Toplevel()
        #self.scopewin.withdraw()

        if config.config_value['baud'] == '115200':
            self.frames['Scope'] = \
                {'row':1, 'column':1, 'rowspan':1, 'columnspan':1, 'relx':0, 'rely':0, 'anchor':tkinter.CENTER, 'sticky':'NEWS',
                        'showlabel':False, 'padx':10, 'pady':10, 'master':self.scopewin}

        #self.frames['CW Keyer Editor'] = \
        #        {'relx':0, 'rely':0, 'anchor':tkinter.CENTER,
        #                'showlabel':True, 'padx':10, 'pady':10, 'master':root}

        self.frames['Frequency'] = \
                {'row':1, 'column':1, 'rowspan':4, 'columnspan':60,
                        'sticky':'NEWS', 'showlabel':False, 'master':root}

        self.frames['CW Keyer'] = \
                {'row':1, 'column':72, 'rowspan':1, 'columnspan':28,
                        'sticky':'NEWS', 'showlabel':False, 'master':root}

        self.frames['CW'] = \
                {'row':2, 'column':72, 'rowspan':1, 'columnspan':28,
                        'sticky':'NEWS', 'showlabel':False, 'master':root}

        self.frames['Break-In/VOX'] = \
                {'row':3, 'column':72, 'rowspan':1, 'columnspan':28,
                        'sticky':'NEWS', 'showlabel':False, 'master':root}

        self.frames['Voice Keyer'] = \
                {'row':4, 'column':72, 'rowspan':1, 'columnspan':28,
                        'sticky':'NEWS', 'showlabel':True, 'master':root}

        self.frames['Meters'] = \
                {'row':6, 'column':1, 'rowspan':1, 'columnspan':33,
                        'sticky':'NEWS', 'showlabel':False, 'master':root}

       # self.frames['Station'] = \
       #         {'row':6, 'column':34, 'rowspan':1, 'columnspan':28,
       #          'sticky':'NS', 'showlabel':True}

        self.frames['SSB'] = \
                {'row':6, 'column':72, 'rowspan':2, 'columnspan':28,
                        'sticky':'NEWS', 'showlabel':False, 'master':root}

        self.frames['Transmit'] = \
                {'row':7, 'column':1, 'rowspan':1, 'columnspan':25,
                        'sticky':'NEWS', 'showlabel':False, 'master':root}

        self.frames['AGC'] = \
                {'row':7, 'column':26, 'rowspan':1, 'columnspan':35,
                        'sticky':'NEWS', 'showlabel':False, 'master':root}

        self.frames['Receive'] = \
                {'row':9, 'column':1, 'rowspan':1, 'columnspan':100,
                        'sticky':'NEWS', 'showlabel':False, 'master':root}

        self.frames['Power'] = \
                {'row':10, 'column':1, 'rowspan':1, 'columnspan':100,
                        'sticky':'NEWS', 'showlabel':False, 'master':root}


    def vfo_clear(self, event, widg):
        """ clear vfo """
        # pylint: disable=W0613
        # pylint: disable=R0201
        widg.delete(0, tkinter.END)
        root.IN_ENTRY = True
        widg.update()


    def con_num_report(self, event, widg, vinc):
        """ spinny for contest number """
        # name = widg.icombut
        # separate ifs
        if event.delta < 0:
            vinc = -1
        if event.delta > 0:
            vinc = 1
        # inx = widg.index("@%d" % event.x)
        #con_num = int(float(widg.get()))
        nnum = int(float(widg.get())) + (1 * vinc)
        if nnum > 9999:
            nnum = 9999
        if nnum < 1:
            nnum = 0
        widg['state'] = 'normal'
        widg.delete(0, tkinter.END)
        if nnum < 1000:
            widg.insert(0, "{:03d}".format(nnum))
        if nnum >= 1000:
            widg.insert(0, "{:04d}".format(nnum))
        widg['state'] = 'readonly'
        CO.send_direct(
            self.send_preamble_bin +
            widg.command +
            bytes.fromhex("{:04d}".format(nnum)) +
            self.suffix_bin)
        widg.update()

    def smallvfo_report(self, event, widg, vinc):
        """ spinny for rit number """
        # pylint: disable=W0613
        #name = widg.icombut
        # separate ifs
        if event.delta < 0:
            vinc = -1
        if event.delta > 0:
            vinc = 1
        inx = widg.index("@%d" % event.x)
        vfo_num = int(float(widg.get())*1000)
        if inx in (0, 2):
            return
        mult = (10 ** (4 - int("010234"[inx]))) # strictly which digit you're moving
        nnum = vfo_num + (mult * vinc)
        if nnum > 9999:
            nnum = 9999
        elif nnum < -9999:
            nnum = -9999
        if nnum < 0:
            p_n = "01" # means "negative" in icom speak
        else:
            p_n = "00"
        v_b = "{:04d}".format(abs(nnum))[2:4]+"{:04d}".format(abs(nnum))[0:2]+p_n
        nnumk = nnum/1000
        widg['state'] = 'normal'
        widg.delete(0, tkinter.END)
        #widg.insert(0, f"{nnumk:+0.3f}")
        widg.insert(0, "{:+0.3f}".format(nnumk))
        widg['state'] = 'readonly'
        CO.send_direct(
            self.send_preamble_bin +
            widg.command +
            bytes.fromhex(v_b) +
            self.suffix_bin)
        widg.update()

    def vfo_report(self, event, widg, vinc):
        """ spinny for vfo """
        if event.delta < 0:
            vinc = -1
        if event.delta > 0:
            vinc = 1

        inx = widg.index("@%d" % event.x)
        # index is 0 thru 9, but gotta add due to "period" spots
        if inx in (-1, 6, 2, 10):
            return
        # set n_v once
        n_v = bytes.fromhex("{:010d}".format(int(widg.get().replace('.', ''))+
                                             (10 ** (9 - int("2304560789"[inx])) * vinc)))[::-1]
        vfo_disp = "{:010,}".format(int((n_v)[::-1].hex())).replace(',', '.')
        widg.delete(0,tkinter.END)
        widg.insert(0,vfo_disp)
        widg.update()
        # set n_v again
        n_v = bytes.fromhex("{:010d}".format(int(widg.get().replace('.', ''))))[::-1]

        cmd = self.send_preamble_bin + widg.command + n_v + self.suffix_bin
        #rcmd = self.receive_preamble_bin + widg.command + n_v + self.suffix_bin
        CO.send_direct(cmd)
        #q=CO.no_buf_direct_receive()
        # just dump it
        #print("q is "+str(q))
        self.vfo_touched=time.time()
        ivalue=int(vfo_disp.replace('.',''))
        self.automode(ivalue,event.widget)
        clear_peaks()


    def dont_qsy(self, event, *args):
        """ read the name of the routine """
        # pylint: disable=R0201
        # pylint: disable=W0613
        root.IN_ENTRY = False
        pollvfo()
        event.widget.update()
        root.focus()

    def do_qsy(self, event, *args):
        """ read the name of the routine """
        # pylint: disable=W0613
        widg = event.widget
        value = event.widget.get()
        if value == "":
            print("huh?")
            widg.delete(0,tkinter.END)
            widg.update()
            root.focus()
            root.IN_ENTRY = True
            handle_escape_key()
            return False
        if value.count('.') == 2:
            fvalue = float(value.replace('.', 'X', 1).replace('.', '').replace('X', '.'))
        if value.count('.') <= 1:
            fvalue = float(value)
        if fvalue <= 74.80000:
            ivalue = int(fvalue*1000000)
        else:
            ivalue = int(fvalue*1000)
        qsy = "{:010d}".format(ivalue)
        # bytes.fromhex is OK here
        bqsy = self.send_preamble_bin + \
                widg.command + \
                bytes.fromhex(qsy)[::-1] + \
                self.suffix_bin

        CO.send_direct(bqsy)
        self.automode(ivalue,event.widget)
        root.IN_ENTRY = False
        event.widget.update()
        root.focus()

    def automode(self,freq,widg):
        if ICOM.widget_variable['band_plan'].get() == "b'\\x00'":
            return

        modebin={'this_vfo_freq':b'\x26\x00', 'that_vfo_freq':b'\x26\x01'}[widg.icombut]
        momo=self.widget_variable[widg.icombut.replace('freq','mdfm')].get()
        possmodes = []
        for b in ICOM.bandplan:
            for m in ICOM.bandplan[b]:
                if freq >= ICOM.bandplan[b][m][0] and freq <= ICOM.bandplan[b][m][1]:
                    possmodes.append(m)
        possmodes.append('AM') # put this on as last item
        pm=possmodes.pop(0)
        for x in ICOM.operating_mode_values:
            if ICOM.operating_mode_values[x] == pm:
                modebin += bytes.fromhex(x)+b'\x00\x01'
                CO.send_direct(ICOM.send_preamble_bin+modebin+ICOM.suffix_bin)

    def run_command(self, hexstring):
        """ this runs a routine based on the string received from the radio
        It has no idea what it is supposed to run until it interprets the
        first few bytes from the received string then determines what CI-V
        command it was, then runs the routine based on that """
        #print('looking for hex string: '+hexstring.hex())
        if hexstring is None:
            return
        temp = self.rxhash
        for h_d in hexstring[len(self.send_preamble_bin):-1]:
            if h_d in temp.keys():
                temp = temp[h_d]
            else:
                if 'fn' in temp.keys():
                    temp['fn'](temp, hexstring)
                else:
                    print("no temp for hexstring: ")
                    print(hexstring)
        #        print('fn '+hexstring.hex())
                return True
        # if you get here you did not find a thing
        if temp == self.rxhash:
            # if you never found a key that matched
            return False

        if temp['name'] == 'FAILURE':
            root.update()
        if temp['name'] not in ('SUCCESS', 'FAILURE'):
            print("****************** CODE NOT ACCOUNTED FOR: "+hexstring.hex())
        return True

    def drop(self, event):
        # pylint: disable=R0201
        """ user un-moused combobox """
        event.widget['state'] = 'normal'

    def undrop(self, event):
        """ user moused combobox """
        ewg=event.widget.get()
        event.widget['state'] = 'readonly'
        event.widget.selection_clear()

        if event.widget.icombut == 'scope_width':
            wid = bytes.fromhex(('0000000000'+ewg+'00')[-12:])[::-1]
            cmd=self.send_preamble_bin + self.widget_object['scope_width'].command + wid + self.suffix_bin
            CO.send_direct(cmd)
            return False

        elif event.widget.icombut == 'scope_edge':
            wid=bytes.fromhex(ewg)
            cmd=self.send_preamble_bin + self.widget_object['scope_edge'].command + wid + self.suffix_bin
            CO.send_direct(cmd)
            return False

        elif event.widget.icombut == 'theme':
            config.config_value['theme'] = ewg
            g_t = self.gui_theme[ewg]
            if g_t != '':
                root.tk_setPalette(**g_t)
                tkinter.ttk.Style().configure("TProgressbar",background='#ff0000',troughcolor='#182c40',thickness=3,troughrelief=tkinter.FLAT)
                tkinter.ttk.Style().configure("TCombobox", **g_t)
            return False

        elif event.widget.icombut == 'agc_time':
            if event.widget.current() == 0:
                if self.widget_variable['nr_on_off'].get() == '01':
                    tkinter.messagebox.showerror(
                        title="Problem",
                        message="Refusing to set AGC to 0.0 with NR turned on.")
                    #root.after(200, released)
                    event.widget['state'] = 'readonly'
                    return False
                s_a = tkinter.messagebox.askyesno(
                    title="Warning!",
                    message="Setting AGC to 0.0 can be loud!  Use caution.  Still choose 0.0?")
                #root.after(200, released)
                if s_a is not True:
                    event.widget['state'] = 'readonly'
                    return False

        # after this point falls thru for all the remaining drop
        # widgets (filter width, serial style)

        event.widget['state'] = 'readonly'
        event.widget.selection_clear()
        if event.widget.command == b'':
            return False
        cmd = self.send_preamble_bin + \
            event.widget.command + \
            bytes.fromhex("{:02d}".format(event.widget.current())) + \
            self.suffix_bin
        CO.send_direct(cmd)
        event.widget.selection_clear()
        return False

    def uneditkeyer(self, *args):
        """ user hit escape """
        #pylint: disable=W0613
        t_c = self.widget_variable['trigger_chan'].get()
        t_ch = "".join((t_c.split("'")[1]).split('\\x'))
        for k_c in self.cw_keyer:
            if '*' in self.cw_keyer_edit[k_c].get() and str(k_c) != str(t_c):
                tkinter.messagebox.showerror(
                    title="D'oh!",
                    message="Trigger channel is "+t_ch+
                    " but there is an asterisk in "+k_c.hex()+"!")
                return
        s_k = tkinter.messagebox.askyesno(
            title="Warning!",
            message="This will write the memory keyer slots as shown.  Do it?")
        if s_k:
            # WE HAVE TO LOOP TWICE AND SAVE ALL THE NON ASTERISK FIRST THEN THE ASTERISK

            for k_s in self.cw_keyer:
                if str(k_s) != str(t_c):
                    self.cw_keyer[k_s] = (self.cw_keyer_edit[k_s].get()+(" "*70))[0:70]
                    cmd = self.send_preamble_bin + \
                        self.widget_object['keyer_send'].command + \
                        k_s + \
                        self.cw_keyer[k_s].encode() + \
                        self.suffix_bin
                    CO.send_direct(cmd)

            for k_s in self.cw_keyer:
                if str(k_s) == str(t_c):
                    self.cw_keyer[k_s] = (self.cw_keyer_edit[k_s].get()+(" "*70))[0:70]
                    cmd = self.send_preamble_bin + \
                        self.widget_object['keyer_send'].command + \
                        k_s + \
                        self.cw_keyer[k_s].encode() + \
                        self.suffix_bin
                    CO.send_direct(cmd)

        self.widget_object['CW Keyer Editor'].place_forget()
        #root.bind("<Escape>", handle_escape_key)
        for k_s in self.cw_keyer:
            self.ekll[k_s].destroy()
            self.ekee[k_s].destroy()
        self.widget_object['CW Keyer Editor'].destroy()
        pollmem()


    def edkeyer(self, *args):
        """ edit keyer dialog """
        #pylint: disable=W0613
        stop_scope_send()
        self.widget_object['CW Keyer Editor'] = tkinter.Frame(root, padx=30, pady=30, bg='blue')
        t_c = self.widget_variable['trigger_chan'].get()
        t_ch = "".join((t_c.split("'")[1]).split('\\x'))
        tkinter.Label(self.widget_object['CW Keyer Editor'], text="Keyer Editor - Esc key to exit",
                      bg='blue', fg='white').grid(row=1, column=1, columnspan=2)
        tkinter.Label(self.widget_object['CW Keyer Editor'], text=" \
                Only channel "+t_ch+" can have an asterisk.  If you changed the \r \
                trigger channel before editing, you must remove the asterisk (*) from the \r \
                previous channel, then put the asterisk in the new trigger channel.  If you \r \
                do not do this, then the previous and new trigger channels may not be saved.  \r \
                The program won't let you type a new asterisk into any slot but the trigger \r \
                channel, and it won't le you do anything to a non trigger channel with an \r \
                asterisk until you remove it.\r \
                ", \
                bg='blue', fg='white').grid(row=2, column=1, columnspan=2)
        #self.ekll = {}
        #self.ekee = {}
        t_c = self.widget_variable['trigger_chan'].get()
        for sl_n in self.cw_keyer:
            self.ekll[sl_n] = tkinter.Label(self.widget_object['CW Keyer Editor'], \
                text=sl_n.hex(), bg='blue', fg='white')
            self.ekll[sl_n].grid(row=int(sl_n.hex())+2, column=1)

            self.ekee[sl_n] = tkinter.Entry(self.widget_object['CW Keyer Editor'], \
                width=70, validate="key")
            self.ekee[sl_n].grid(row=int(sl_n.hex())+2, column=2, sticky='NEWS')

            self.ekee[sl_n].configure(font='courier 10')
            self.ekee[sl_n].configure(textvariable=self.cw_keyer_edit[sl_n])
            if str(sl_n) == str(t_c):
                self.ekee[sl_n]['validatecommand'] = (self.ekee[sl_n].register(keyercononly), '%P')
            else:
                self.ekee[sl_n]['validatecommand'] = (self.ekee[sl_n].register(keyeronly), '%P')

        self.widget_object['CW Keyer Editor'].place(relx=0.5, rely=0.5, anchor=tkinter.CENTER)
        self.widget_object['CW Keyer Editor'].grab_set()
        root.bind("<Escape>", self.uneditkeyer)
        self.widget_object['CW Keyer Editor'].wait_window()




    def slideractive(self, event):
        """ update touched time when moving stuff """
        # pylint: disable=W0613
        #self.gui_touched = time.time()
        pass

    def wheel(self, event, whee):
        """ mouse wheely thing """
        event.widget.set((event.widget.get() + (event.widget['resolution']*whee)))
        self.slider(event)

    def slider(self, event):
        """ when moving a slidey around """
        vals = list(event.widget.values)
        lower = vals[0]
        upper = vals[-1]
        s_pos = event.widget.get()
        if event.widget.type == 'ScaleFF':
            if event.widget.icombut == 'dot_dash':
                binv = s_pos
            else:
                binv = s_pos - 1
            #oldval = self.last_polled_value[event.widget.icombut].get()
            newval = bytes.fromhex(('0000'+str(binv))[-2:])
        else:
            binv = round(255*((s_pos - lower) / (upper - lower)))
            #oldval = self.last_polled_value[event.widget.icombut].get()
            newval = bytes.fromhex(('0000'+str(binv))[-4:])
        CO.send_direct(
            self.send_preamble_bin + event.widget.command + newval + self.suffix_bin)

    def cwsend(self, event):
        """ send string of cw using icom keyer """
        msg = event.widget.get()
        CO.send_direct(self.send_preamble_bin + \
            b'\x17' + bytes(msg.encode()) + self.suffix_bin)
        event.widget.delete(0, tkinter.END)
        event.widget.update()

    def tog(self, event):
        """ big ass routine when a button is hit """
        command = event.widget.command
        if event.widget.type == 'ListBox':
            if event.widget.icombut == 'set_mem_modebox':
                m_sl = bytes.fromhex('00'+event.widget.get(tkinter.ACTIVE)[0:2])
                y_n = tkinter.messagebox.askyesno(
                    title="Warning!",
                    message="This puts the memory contents into the VFO.  Want to load memory "+
                    m_sl.hex()+" into VFO?")
                if y_n:
                    imem = int(m_sl.hex())-1
                    mc_n = self.memory_channel[imem]
                    # this chooses the radio channel the user clicked
                    #print("going to memory channel "+str(m_sl))
                    CO.send_direct(self.send_preamble_bin + \
                        b'\x08' + m_sl + self.suffix_bin)
                    # this goes to VFO mode
                    CO.send_direct(self.send_preamble_bin + \
                        b'\x07' + self.suffix_bin)

                    # this saves the current split value (on/off)
                    #c_s = self.widget_variable['split_on_off'].get()
                    #c_sh = "".join((c_s.split("'")[1]).split('\\x'))
                    #cursplit = bytes.fromhex(c_sh)

                    # turn split on to force copy of both sides
                    CO.send_direct(self.send_preamble_bin + \
                        b'\x0F\x01' + self.suffix_bin)

                    # this copies it to the vfo
                    CO.send_direct(self.send_preamble_bin + \
                        b'\x0a' + self.suffix_bin)

                    # Put split value from memory into radio
                    CO.send_direct(self.send_preamble_bin + \
                        b'\x0F' + bytes.fromhex('0'+str(mc_n.splitraw)) + self.suffix_bin)

                    # this goes to VFO mode
                    CO.send_direct(self.send_preamble_bin + \
                        b'\x07' + self.suffix_bin)

                    #root.after(200, released)

        elif event.widget.type == 'ButtonMulti':
            if command == '':
                return
            if event.widget.icombut == 'keyer_send':
                k_num = event.widget.hardvalue
                t_c = self.widget_variable['trigger_chan'].get()
                for msg in textwrap.wrap(self.cw_keyer[k_num], 29):
                    msgs = msg+" "
                    if '*' in msgs and str(k_num) == t_c:
                        n_sty = self.widget_object['contestnums'].get()
                        c_num = self.widget_object['contest_num'].get()
                        #t_c = self.widget_variable['trigger_chan'].get()
                        #newnm = bytes.fromhex(f"{int(nm)+1:04d}")
                        newnm = bytes.fromhex("{:04d}".format(int(c_num)+1))

                        if n_sty == '190->ANO':
                            c_num = c_num.replace('1', 'A').replace('9', 'N').replace('0', 'O')
                        if n_sty == '190->ANT':
                            c_num = c_num.replace('1', 'A').replace('9', 'N').replace('0', 'T')
                        if n_sty == '190->1NO':
                            c_num = c_num.replace('9', 'N').replace('0', 'O')
                        if n_sty == '190->1NT':
                            c_num = c_num.replace('9', 'N').replace('0', 'T')

                        msgs = msgs.replace('*', str(c_num))
                        CO.send_direct(
                            self.send_preamble_bin +
                            self.widget_object['contest_num'].command +
                            newnm +
                            self.suffix_bin)
                    # send actual message (doctored or not)
                    CO.send_direct(
                        self.send_preamble_bin +
                        b'\x17' +
                        bytes(msgs.encode()) +
                        self.suffix_bin)
            elif event.widget.icombut == 'vkeyer_send':
                CO.send_direct(
                    self.send_preamble_bin +
                    command +
                    event.widget.hardvalue +
                    self.suffix_bin)
        elif event.widget.type == 'Button':
            # special if power
            if event.widget.icombut == 'set_power_on':
                cmd = self.powerpfx_bin + \
                    self.send_preamble_bin + \
                    command + \
                    self.suffix_bin
                root.after(2000, pollall)
                root.after(2500, stuff_startup_cmds)
                root.after(3000, pollall)
                root.after(3500, stuff_startup_cmds)
                root.after(4000, pollall)
                root.after(4500, stuff_startup_cmds)
            elif event.widget.icombut == 'digi':
                    jtdx=get_digi_prog()

                    if jtdx is None:
                        return
                    loggersock.shut()
                    rig_save = list()
                    # turn off scope sending
                    ICOM.status_line.set("Turning off scope sending...")
                    CO.send_direct(ICOM.send_preamble_bin + ICOM.binary_send_item['scopesenddata']+b'\x00' + ICOM.suffix_bin)
                    CO.send_direct(ICOM.send_preamble_bin + ICOM.binary_send_item['scopesenddata']+b'\x00' + ICOM.suffix_bin)
                    ICOM.status_line.set("Quiescing...")
                    for x in range(0,40):
                        q=CO.no_buf_direct_receive()

                    ICOM.status_line.set("Setting radio up for digital.")
                    root.update()


                    setting_get_and_set('set_vfo_mode',b'\x00')
                    setting_get_and_set('scopesenddata',b'\x00')
                    setting_get_and_set('set_vfo_mode',b'\x00')
                    setting_get_and_set('scopesenddata',b'\x00')
                    #quiesce stream
                    for a in range(0,1000):
                        dummy=CO.no_buf_direct_receive()
                    time.sleep(.1)

                    # SET UP SPECIAL VARS AND RE DO THEM BY HAND

                    rig_save.append(setting_get_and_set('echo_on_off',b'\x01'))
                    rig_save.append(setting_get_and_set('transceive_on_off',b'\x00'))
                    rig_save.append(setting_get_and_set('scopesenddata',b'\x00'))
                    rig_save.append(setting_get_and_set('rit_on_off',b'\x00'))
                    rig_save.append(setting_get_and_set('xit_on_off',b'\x00'))
                    rig_save.append(setting_get_and_set('preamp_type',b'\x00'))
                    rig_save.append(setting_get_and_set('level_af',b'\x00'))
                    rig_save.append(setting_get_and_set('nb_on_off',b'\x00'))
                    rig_save.append(setting_get_and_set('nr_on_off',b'\x00'))
                    rig_save.append(setting_get_and_set('anotch_on_off',b'\x00'))
                    rig_save.append(setting_get_and_set('notch_on_off',b'\x00'))

                    rig_save.append(setting_get_and_set('split_on_off',b'\x00'))

                    oldmode_agc_type  =setting_get('agc_type')
                    oldmode_agc_time  =setting_get('agc_time')
                    oldmode_filter_bw =setting_get('cur_rx_bw')

                    rig_save.append(setting_get_and_set('that_vfo_freq',b'\x01')) # sending bullcrap value don't care
                    rig_save.append(setting_get_and_set('this_vfo_freq',b'\x00')) # sending bullcrap value don't care

                    rig_save.append(setting_get_and_set('that_vfo_mdf',b'\x01\x01\x01'))
                    rig_save.append(setting_get_and_set('this_vfo_mdf',b'\x01\x01\x01'))

                    usbdigi_agc_type  =setting_get('agc_type')
                    usbdigi_agc_time  =setting_get('agc_time')
                    usbdigi_filter_bw =setting_get('cur_rx_bw')

                    # force wide and no agc but don't save
                    setting_get_and_set('agc_type',b'\x03')
                    usbdigi_agc_time2=setting_get_and_set('agc_time',b'\x00')
                    setting_get_and_set('cur_rx_bw',b'\x31')
                    setting_get_and_set('cur_rx_bw',b'\x40')


                    for a in range(0,1000):
                        CO.direct_receive()
                        ICOM.run_command(CO.recvq.get(False))
                        root.update()

                    ICOM.status_line.set("Executing outside program...")
                    root.update()
                    time.sleep(.5)

                    saveattr=termios.tcgetattr(CO.ser)

                    scope_was_showing=False
                    if self.scopewin.winfo_ismapped():
                        scope_was_showing=True
                        hide_scope()
                    root.iconify()
                    root.withdraw()
                    root.update()


                    #os.execv(jtdx,('',))
                    os.system(jtdx)
                    root.deiconify()
                    root.update()
                    ICOM.status_line.set("Preparing to restore radio...")
                    root.update()

                    for xx in range(0,200):
                        receivecycle()
                        root.update()

                    ICOM.status_line.set("Restoring radio.")
                    root.update()
                    for x in range(0,10):
                        setting_get_and_set('echo_on_off',b'\x01')
                        time.sleep(.03)
                    for x in range(0,10):
                        setting_get_and_set('echo_on_off',b'\x00')
                        time.sleep(.03)
                    print("sending saved usb digi filter and agc...")
                    # set the "slow" time back
                    CO.send_direct(usbdigi_agc_time2[1].replace(ICOM.receive_preamble_bin,ICOM.send_preamble_bin))
                    time.sleep(.1)
                    # switch to the prev type
                    CO.send_direct(usbdigi_agc_type[1].replace(ICOM.receive_preamble_bin,ICOM.send_preamble_bin))
                    time.sleep(.1)
                    # set the old type time back
                    CO.send_direct(usbdigi_agc_time[1].replace(ICOM.receive_preamble_bin,ICOM.send_preamble_bin))
                    time.sleep(.1)
                    CO.send_direct(usbdigi_filter_bw[1].replace(ICOM.receive_preamble_bin,ICOM.send_preamble_bin))
                    time.sleep(.1)
                    for xx in reversed(rig_save):
                        try:
                            cmd=xx[1].replace(ICOM.receive_preamble_bin,ICOM.send_preamble_bin)
                        except:
                            # if above breaks, send an echo off
                            print("previous set_and_get returned nothing so doing an echo")
                            cmd=ICOM.send_preamble_bin + b'\x1a\x05\x00\x75\x00' + ICOM.suffix_bin

                        CO.send_direct(cmd)
                        print("rig sent "+xx[0]+" "+cmd.hex())
                        time.sleep(.1)
                    print("sending saved old mode filter and agc...")
                    CO.send_direct(oldmode_agc_type[1].replace(ICOM.receive_preamble_bin,ICOM.send_preamble_bin))
                    time.sleep(.1)
                    CO.send_direct(oldmode_agc_time[1].replace(ICOM.receive_preamble_bin,ICOM.send_preamble_bin))
                    time.sleep(.1)
                    CO.send_direct(oldmode_filter_bw[1].replace(ICOM.receive_preamble_bin,ICOM.send_preamble_bin))
                    time.sleep(.1)

                    setting_get_and_set('echo_on_off',b'\x00')
                    #for xx in reversed(rig_save):
                    #    cmd=xx[1].replace(ICOM.receive_preamble_bin,ICOM.send_preamble_bin)
                    #    CO.send_direct(cmd)
                    #    print("sent "+cmd.hex())
                    #    time.sleep(.03)

                    for xx in range(0,1000):
                        receivecycle()
                        root.update()

                    if scope_was_showing:
                        try:
                            show_scope()
                        except:
                            pass

                    termios.tcsetattr(CO.ser,termios.TCSANOW,saveattr)
                    ICOM.status_line.set("Radio restored!")
                    root.update()
                    root.after(1000,erase_status_line)

                    return

            elif event.widget.icombut == 'vscope':
                if config.config_value['baud'] == '115200':
                    if self.scopewin.winfo_ismapped():
                        hide_scope()
                    else:
                        show_scope()
                    return
                else:
                    tkinter.messagebox.showerror(
                        title="Problem",
                        message="The ICOM IC-7300 will not send scope data " + \
                                "unless its USB CI-V port baud is set to 115,200 " + \
                                "baud and Unlink from Remote is chosen.")
                    return
            elif event.widget.icombut == 'rit_zero':
                cmd = self.send_preamble_bin + \
                    self.widget_object['rit_freq'].command + \
                    bytes.fromhex('000000') + \
                    self.suffix_bin
            elif event.widget.icombut == 'reconfig':
                config.force_reconfig = True
                config.read_cfg()
                #if os.path.exists(config.config_filename):
                #    os.remove(config.config_filename)
                #restart_prog()
                return
            elif event.widget.icombut == 'edkeyer':
                self.edkeyer()
                return
            elif event.widget.icombut == 'refresh':
                root.after(100, pollall)
                # not sending a command
                return
            elif event.widget.icombut == 'rename_mem':
                imem = self.widget_object['set_mem_modebox'].curselection()
                if imem == ():
                    tkinter.messagebox.showerror(
                        title="D'oh!",
                        message="Click one of the memories in the MEM box to rename it.")
                    #root.after(200, released)
                    return
                if imem[0] not in self.memory_channel.keys():
                    tkinter.messagebox.showerror(
                        title="D'oh!",
                        message="Can't rename an empty memory.")
                    return
                stop_scope_send()
                n_mn = tkinter.simpledialog.askstring(
                    "Input:",
                    "10 Chars or fewer, name memory "+str(imem[0]+1)+"!",
                    parent=root)
                start_scope_send()
                #root.after(200, released)
                if n_mn is None:
                    return
                if len(n_mn) > 10:
                    tkinter.messagebox.showerror(
                        title="D'oh!",
                        message="Sorry, that was more than ten characters.")
                    #root.after(200, released)
                    return
                if n_mn:
                    mcon = bytes.fromhex(
                        '00'+self.widget_object['set_mem_modebox'].get(tkinter.ACTIVE)[0:2])
                    m_cn = self.memory_channel[imem[0]]
                    nm_h = m_cn.hex[0:58]+(n_mn+'          ').encode().hex()[0:20]
                    cmd = self.send_preamble_bin + \
                        b'\x1a\x00' + \
                        mcon + \
                        bytes.fromhex(nm_h) + \
                        self.suffix_bin
                    CO.send_direct(cmd)
                    self.widget_object['set_mem_modebox'].insert(imem[0], " ")
                    self.widget_object['set_mem_modebox'].delete(imem[0]+1)
                    root.after(300, pollmem)
                return
            elif event.widget.icombut == 'clear_mem':
                imem = self.widget_object['set_mem_modebox'].curselection()
                if imem == ():
                    tkinter.messagebox.showerror(
                        title="D'oh!",
                        message="Click one of the memories in the MEM box to erase it.")
                    #root.after(200, released)
                    return
                if imem[0] not in self.memory_channel.keys():
                    tkinter.messagebox.showerror(
                        title="D'oh!",
                        message="Can't erase an empty memory.")
                    return
                y_n = tkinter.messagebox.askyesno(
                    title="HEY!",
                    message="This ERASES memory "+str(imem[0]+1)+"!  Proceed?")
                if y_n:
                    mm_c = bytes.fromhex(
                        '00'+self.widget_object['set_mem_modebox'].get(tkinter.ACTIVE)[0:2])
                    CO.send_direct(self.send_preamble_bin + \
                        b'\x08' + \
                        mm_c + \
                        self.suffix_bin)
                    cmd = self.send_preamble_bin + \
                        b'\x1a\x00' + \
                        mm_c + \
                        b'\xff' + \
                        self.suffix_bin
                    CO.send_direct(cmd)
                    self.widget_object['set_mem_modebox'].insert(imem[0], " ")
                    self.widget_object['set_mem_modebox'].delete(imem[0]+1)
                    root.after(300, pollmem)
                return
            elif event.widget.icombut == 'set_vfo_mem':
                imem = self.widget_object['set_mem_modebox'].curselection()
                if imem == ():
                    tkinter.messagebox.showerror(
                        title="D'oh!",
                        message="Click one of the memories in the MEM box to save to it.")
                    return
                if imem[0] in self.memory_channel.keys():
                    tkinter.messagebox.showwarning(
                        title="D'oh!",
                        message="This memory has something in it already.  \
                                If you want to overwrite it, say yes at the next prompt.")
                y_n = tkinter.messagebox.askyesno(
                    title="HEY!",
                    message="This puts the VFO contents into memory "+str(imem[0]+1)+"!  Proceed?")
                mm_c = bytes.fromhex(
                    '00'+self.widget_object['set_mem_modebox'].get(tkinter.ACTIVE)[0:2])
                if y_n:
                    mm_c = bytes.fromhex(
                        '00'+self.widget_object['set_mem_modebox'].get(tkinter.ACTIVE)[0:2])
                    CO.send_direct(self.send_preamble_bin +
                                             b'\x08' +
                                             mm_c +
                                             self.suffix_bin)
                    CO.send_direct(self.send_preamble_bin +
                                             b'\x09' +
                                             self.suffix_bin)
                    self.widget_object['set_mem_modebox'].delete(imem[0])
                    self.widget_object['set_mem_modebox'].insert(imem[0], " ")
                    self.widget_object['set_mem_modebox'].selection_set(imem[0])

                    pollmem()
                    #root.after(200, released)
                return
            elif event.widget.icombut == 'timesync':
                timesync()
                # not sending a command
                return
            elif event.widget.icombut == 'quit':
                quit_prog(False)
                # not sending a command
                return
            elif event.widget.icombut == 'set_power_off':
                if self.scopewin.winfo_ismapped():
                    scope_was_showing=True
                    hide_scope()
                quit_prog(True)
                # not sending a command
                return
            else:
                #print("sending "+command.hex())
                cmd = self.send_preamble_bin + command + self.suffix_bin

            CO.send_direct(cmd)

            if 'vfo_' in event.widget.icombut:
                CO.send_direct_command('this_vfo_freq')
                CO.send_direct_command('that_vfo_freq')
                CO.send_direct_command('this_vfo_mdf')
                CO.send_direct_command('that_vfo_mdf')

        elif event.widget.type == 'RadiobuttonMulti':
            if command == '':
                return
            #oldval = self.last_polled_value[event.widget.icombut].get()
            #curval = event.widget.hardvalue
            CO.send_direct(self.send_preamble_bin +
                                     command +
                                     event.widget.hardvalue +
                                     self.suffix_bin)
            #receivecycle()
            CO.send_direct(self.send_preamble_bin +
                                     command +
                                     self.suffix_bin)
            #receivecycle()
        elif event.widget.type == 'RadiobuttonTog':
            oldval = self.last_polled_value[event.widget.icombut].get()
            curval = event.widget.hardvalue
            for w_v in event.widget.values:
                if str(event.widget.values[w_v]) != oldval:
                    curval = event.widget.values[w_v]
                    break
            cmd = self.send_preamble_bin + command + curval + self.suffix_bin
            CO.send_direct(cmd)
            self.last_polled_value[event.widget.icombut].set(curval)
            self.widget_variable[event.widget.icombut].set(curval)

        elif event.widget.type == 'MDFSet':
            oldval = self.last_polled_value[event.widget.icombut].get()
            curval = event.widget.hardvalue
            mdf = event.widget.icombut[-1]
            #grp = event.widget.icombut[:-1]
            mdf_m = self.last_polled_value[event.widget.icombut[:-1]+'m'].get()
            mdf_d = self.last_polled_value[event.widget.icombut[:-1]+'d'].get()
            mdf_f = self.last_polled_value[event.widget.icombut[:-1]+'f'].get()
            if mdf == 'm':
                mdf_m = str(curval)
            if mdf == 'd':
                mdf_d = {'00':'01', '01':'00'}[mdf_d]
            if mdf == 'f':
                mdf_f = str(curval)

            CO.send_direct(self.send_preamble_bin +
                                     command +
                                     bytes.fromhex(mdf_m + mdf_d + mdf_f) +
                                     self.suffix_bin)
            CO.send_direct(self.send_preamble_bin +
                                     command +
                                     self.suffix_bin)
            #receivecycle()
            #receivecycle()
        event.widget.update




    # name bytes type range
    def makebutt(self, name, hexstring, widg_type, values, num_of_bytes_returned, pollme, win,
                 rrow, ccol, rrowspan, ccolspan, title, bias, slider_res, width, asciimsg=""):
        """ create the widget for each icom control """
        # self is the class
        # name is the name of the control
        # hexstring is from the icom manual
        # widg type is arbitrary widget type
        # values is range of values for the widget, e.g. 1 thru 10
        # num_of_bytes_returned is how many bytes to expect for "variable"
        # pollme tells program to poll this control from radio and update it
        # win is the window to place the widget, usually a frame like 'cw' or 'vfo'
        # rrow, row in the win to put widg
        # ccol, col in the win to put widg
        # rrowspan, how tall in rows
        # ccolspan, how wide in col
        # title for widg
        # bias to apply for sliders whose lowest / highest don't conform to 0000/0255
        # this builds the search array for incoming RX from serial
        # it also builds the widgets, mostly

        # rxhash is the large dict of values arranged by hex command pairs
        temp = self.rxhash
        for h_d in hexstring:
            temp.setdefault(h_d, {})
            temp = temp[h_d]

        temp.setdefault('name', name)
        temp.setdefault('command', hexstring)
        temp.setdefault('num_of_bytes_returned', num_of_bytes_returned)

        if name == 'keyer_send':
            temp.setdefault('fn', _process_keyer_send)
        elif widg_type in ("Scale0255", "Progressbar"):
            temp.setdefault('fn', _process_scale0255_progressbar)
        elif widg_type == "ScaleFF":
            temp.setdefault('fn', _process_scaleff)
        elif widg_type == "MDFSet":
            temp.setdefault('fn', _process_mdfset)
        elif widg_type == "VFOSet":
            temp.setdefault('fn', _process_vfoset)
        elif widg_type == "Software":
            if name in ('READ FREQ LOGGER','READ MODE LOGGER','SEND FREQ LOGGER','SEND MODE LOGGER'):
                temp.setdefault('fn', _process_logger)
            if name == 'scope_fill_color':
                temp.setdefault('fn', _process_color)
            if name == 'scope_line_color':
                temp.setdefault('fn', _process_color)
            if name == 'scope_peak_color':
                temp.setdefault('fn', _process_color)
            if name == 'scopedata':
                temp.setdefault('fn', _process_scope)
            if name == 'ovf':
                temp.setdefault('fn', _process_ovf)
            elif name == 'radiodate':
                temp.setdefault('fn', _process_radio_date)
            elif name == 'radiotime':
                temp.setdefault('fn', _process_radio_time)
            elif name == 'radiotz':
                temp.setdefault('fn', _process_radio_tz)
            elif name == 'my_call':
                temp.setdefault('fn', _process_my_call)
            elif name == 'mem_ch':
                temp.setdefault('fn', _process_mem_ch)
        elif widg_type == "SmallVFO":
            if name == 'contest_num':
                temp.setdefault('fn', _process_contest_num)
            elif name == 'rit_freq':
                temp.setdefault('fn', _process_rit_freq)
        elif widg_type == "LabelCombobox":
            if name == 'scope_width':
                temp.setdefault('fn', _process_scope_width)
            elif name == 'scope_edge':
                temp.setdefault('fn', _process_scope_edge)
            elif name == 'contestnums':
                temp.setdefault('fn', _process_contestnums)
            elif name == 'cur_rx_bw':
                temp.setdefault('fn', _process_cur_rx_bw)
            elif name == 'agc_time':
                temp.setdefault('fn', _process_agc_time)
        else:
            if hexstring == b'':
                print("not setting \"other\" for name "+str(name)+", hexstring "+str(hexstring))
            else:
                temp.setdefault('fn', _process_other)

        if 'fn' not in temp.keys():
            temp.setdefault('fn', _process_nothing)

        self.binary_send_item.setdefault(name, hexstring)

        if pollme > 0:
            # exclusions for weird things
            if name not in ('mem_ch', 'keyer_send', 'vkeyer_send'):
                self.poll_type[name] = pollme


        # CREATE THE FRAME FOR THE GROUP OF WIDGETS ONLY IF IT DOES NOT EXIST YET
        if win not in self.widget_object.keys():
            if win != '':
                tfrm = self.frames[win]
                if tfrm['showlabel']:
                    self.widget_object[win] = tkinter.LabelFrame(tfrm['master'],
                                                                 text=win,
                                                                 relief=tkinter.FLAT,
                                                                 borderwidth=1)
                else:
                    self.widget_object[win] = tkinter.Frame(tfrm['master'],
                                                            relief=tkinter.FLAT,
                                                            borderwidth=1)

                self.widget_object[win].grid(row=tfrm['row'], column=tfrm['column'],
                                             rowspan=tfrm['rowspan'], columnspan=tfrm['columnspan'],
                                             sticky=tfrm['sticky'], padx=0)

        if widg_type == 'Software':

            self.widget_object[name] = tkinter.Frame(root, relief=tkinter.FLAT, borderwidth=2)
            # this frame gets ignored, just for a var to be held
            if name in ('my_call', 'radiodate', 'radiotime', 'radiotz', 'ovf'):
                self.widget_object[name].icombut = name
                self.widget_object[name].command = hexstring

            if name == 'mem_ch':
                for x_v in range(1, 100):
                    name2 = 'mem_ch'+"{:04d}".format(x_v)
                    memcmd = b'\x1a\x00'+bytes.fromhex("{:04d}".format(x_v))
                    self.poll_type[name2] = pollme
                    self.widget_object[name2] = tkinter.Frame(
                        root, relief=tkinter.FLAT, borderwidth=2)
                    self.widget_object[name2].command = memcmd
                    self.binary_send_item.setdefault(name2, memcmd)

        elif widg_type == 'LabelCombobox':
            if name in ('cur_rx_bw', 'agc_time', 'contestnums', 'theme', 'scope_width', 'scope_edge','scope_mult'):
                self.widget_object[name] = \
                        LabelCombobox(self.widget_object[win],
                                      labeltext=title,
                                      width=width,
                                      state='readonly',
                                      font='Courier 10')
                if name == 'contestnums':
                    self.widget_object[name]['values'] = self.keyertypes
                elif name in ('theme','scope_width','scope_edge','scope_mult'):
                    self.widget_object[name]['values'] = values
                if name == 'scope_mult':
                    self.widget_object[name].set("x1")

                self.widget_object[name].grid(
                    row=rrow, column=ccol, rowspan=rrowspan, columnspan=ccolspan)
                self.widget_object[name].bind('<ButtonPress-1>', self.drop)
                self.widget_object[name].bind('<ButtonRelease-1>', self.undrop)
                self.widget_object[name].bind('<<ComboboxSelected>>', self.undrop)
                self.widget_object[name].icombut = name

        elif widg_type == 'ListBox':
            if name == 'set_mem_modebox':
                ## HARD CODED MEMORY BUTTON
                self.widget_object[name] = \
                        tkinter.Listbox(self.widget_object[win], \
                        width=34, \
                        font='Courier 10', \
                        selectmode='NONE')
                        # selectmode='SINGLE')
                self.widget_object[name].grid(
                    row=rrow, column=ccol, rowspan=rrowspan, columnspan=ccolspan)
                self.widget_object[name].bind('<Double-Button-1>', self.tog)
                for dummy in range(1, 100):
                    self.widget_object[name].insert(tkinter.END, " ")

        elif widg_type == 'ButtonMulti':
            # right now only the keyer and voice keyer
            self.widget_variable[name] = tkinter.StringVar()
            self.last_polled_value[name] = tkinter.StringVar()
            self.widget_object[name] = tkinter.Frame(self.widget_object[win])
            self.widget_object[name].grid(
                row=rrow, column=ccol, rowspan=rrowspan, columnspan=ccolspan)
            w_row = 1
            w_col = 1
            for w_va in values:
                #cmd = self.send_preamble_hex+hexstring+str(values[w_va])+self.suffix_hex
                self.widget_object[name+str(values[w_va])] = \
                        tkinter.Button(self.widget_object[name],
                                       text=w_va,
                                       padx=0,
                                       pady=0,
                                       width=width)
                self.widget_object[name+str(values[w_va])].bind('<ButtonRelease-1>', self.tog)
                self.widget_object[name+str(values[w_va])].grid(row=w_row, column=w_col)
                self.widget_object[name+str(values[w_va])].icombut = name
                self.widget_object[name+str(values[w_va])].command = hexstring
                self.widget_object[name+str(values[w_va])].hardvalue = values[w_va]
                self.widget_object[name+str(values[w_va])].type = widg_type
                # even though not flagged as poll in the declaration, specially poll these
                #self.POLLME.append(name+str(values[w_va]))
                if pollme > 0:
                    self.poll_type[name+str(values[w_va])] = pollme
                self.binary_send_item.setdefault(name+str(values[w_va]), hexstring+values[w_va])
                #w_row = w_row+1
                w_col = w_col+1
                if w_col > 4:
                    w_col = 1
                    w_row = w_row+1

        elif widg_type == 'LabelEntry':
            if name == 'freeform_send':
                self.widget_object[name] = \
                         LabelEntry(self.widget_object[win], \
                         labeltext=title, \
                         width=width, \
                         validate="key", \
                         font='Courier 8')
                self.widget_object[name].grid(
                    row=rrow, column=ccol, rowspan=rrowspan, columnspan=ccolspan)
                self.widget_object[name].bind("<KP_Enter>", self.cwsend)
                self.widget_object[name].bind("<Return>", self.cwsend)
                v_c = self.widget_object[name]
                v_c['validatecommand'] = (v_c.register(cwonly), '%P')

        elif widg_type == 'Label':
            self.widget_object[name] = tkinter.Label(self.widget_object[win],
                                                     textvariable=title,
                                                     justify="center",
                                                     width=width,
                                                     padx=0,
                                                     pady=0)
            self.widget_object[name].grid(row=rrow,
                                          column=ccol,
                                          rowspan=rrowspan,
                                          columnspan=ccolspan)
            if name == 'callbrag':
                self.widget_object[name].config(font='Courier 20 bold')
            if name in ('datedisp', 'timedisp'):
                self.widget_object[name].config(font='Courier 12 bold')
            if name in ('status_line', 'foofoo'):
                self.widget_object[name].config(font='Courier 10 bold')
            if name == 'ovfb':
                self.widget_object[name].config(font='Courier 12 bold')
                self.widget_object[name].config(anchor='w')
                self.widget_object[name].config(justify='left')
                self.widget_object[name].grid_configure(sticky='w')


        elif widg_type == 'Button':
            self.widget_object[name] = tkinter.Button(self.widget_object[win],
                                                      text=title,
                                                      justify="center",
                                                      width=width,
                                                      padx=0,
                                                      pady=0)
            self.widget_object[name].bind('<ButtonRelease-1>', self.tog)
            self.widget_object[name].grid(
                row=rrow, column=ccol, rowspan=rrowspan, columnspan=ccolspan)

        elif widg_type == 'SmallVFO':
            self.widget_variable[name] = tkinter.StringVar()
            self.last_polled_value[name] = tkinter.StringVar()
            self.widget_object[name] = tkinter.Entry(self.widget_object[win],
                                                     font="Helvetica 12 bold",
                                                     state='readonly',
                                                     justify="right",
                                                     width=width,
                                                     bg='grey',
                                                     validate="key",
                                                     textvariable=self.widget_variable[name])
            self.vfo_widget.append(self.widget_object[name])
            self.widget_object[name].grid(
                row=rrow, column=ccol, rowspan=rrowspan, columnspan=ccolspan)
            if name == 'contest_num':
                self.widget_object[name].bind("<MouseWheel>", \
                    lambda event, ww=self.widget_object[name]: self.con_num_report(event, ww, +1))
                self.widget_object[name].bind("<Button-4>", \
                    lambda event, ww=self.widget_object[name]: self.con_num_report(event, ww, +1))
                self.widget_object[name].bind("<Button-5>", \
                    lambda event, ww=self.widget_object[name]: self.con_num_report(event, ww, -1))
            if name == 'rit_freq':
                self.widget_object[name].bind("<MouseWheel>", \
                    lambda event, ww=self.widget_object[name]: self.smallvfo_report(event, ww, +1))
                self.widget_object[name].bind("<Button-4>", \
                    lambda event, ww=self.widget_object[name]: self.smallvfo_report(event, ww, +1))
                self.widget_object[name].bind("<Button-5>", \
                    lambda event, ww=self.widget_object[name]: self.smallvfo_report(event, ww, -1))

            v_c = self.widget_object[name]
            v_c['validatecommand'] = (v_c.register(numonly), '%P')

        elif widg_type == 'VFOSet':
            self.widget_variable[name] = tkinter.StringVar()
            self.last_polled_value[name] = tkinter.StringVar()
            self.widget_object[name] = tkinter.Entry(self.widget_object[win],
                                                     font="Helvetica 36 bold",
                                                     justify="right",
                                                     width=width,
                                                     bg='#aaffaa',
                                                     validate="key",
                                                     textvariable=self.widget_variable[name])
            self.vfo_widget.append(self.widget_object[name])
            self.widget_object[name].grid(
                row=rrow, column=ccol, rowspan=rrowspan, columnspan=ccolspan)

            self.widget_object[name].bind("<MouseWheel>", \
                lambda event, ww=self.widget_object[name]: self.vfo_report(event, ww, +1))

            self.widget_object[name].bind("<Button-4>", \
                lambda event, ww=self.widget_object[name]: self.vfo_report(event, ww, +1))

            self.widget_object[name].bind("<Button-5>", \
                lambda event, ww=self.widget_object[name]: self.vfo_report(event, ww, -1))

            self.widget_object[name].bind("<Double-Button-1>", \
                lambda event, ww=self.widget_object[name]: self.vfo_clear(event, ww))

            self.widget_object[name].bind("<Double-Button-1>", \
                lambda event, ww=self.widget_object[name]: self.vfo_clear(event, ww))

            self.widget_object[name].bind("<FocusIn>", \
                lambda event, ww=self.widget_object[name]: self.vfo_clear(event, ww))

            self.widget_object[name].bind("<FocusOut>", \
                lambda event, ww=self.widget_object[name]: self.dont_qsy)

            self.widget_object[name].bind("<Tab>", self.dont_qsy)
            self.widget_object[name].bind("<Return>", self.do_qsy)
            self.widget_object[name].bind("<KP_Enter>", self.do_qsy)
            v_c = self.widget_object[name]
            v_c['validatecommand'] = (v_c.register(numonly), '%P')

        elif widg_type == 'MDFSet':
            gridloc = {'f1':[1, 1], 'm3':[1, 2], 'm2':[1, 3], 'm4':[1, 4], \
                     'f2':[2, 1], 'm1':[2, 2], 'm5':[2, 3], 'm8':[2, 4], \
                     'f3':[3, 1], 'm0':[3, 2], 'm7':[3, 3], 'd1':[3, 4]}
            self.widget_object[name] = tkinter.Frame(self.widget_object[win])
            self.widget_object[name].grid(
                row=rrow, column=ccol, rowspan=rrowspan, columnspan=ccolspan)
            for m_d_f in 'mdf':
                self.widget_variable[name+m_d_f] = tkinter.StringVar()
                self.last_polled_value[name+m_d_f] = tkinter.StringVar()
                if m_d_f == 'm':
                    mdf_row = 1
                    self.widget_variable[name+m_d_f] = tkinter.StringVar()
                    self.last_polled_value[name+m_d_f] = tkinter.StringVar()
                    for s_m in self.modes:
                        self.widget_object[name+m_d_f+self.modes[s_m]] = tkinter.Radiobutton(
                            self.widget_object[name],
                            text=s_m,
                            padx=0,
                            pady=0,
                            width=width,
                            selectcolor='#aaffaa',
                            indicator='no',
                            value=self.modes[s_m],
                            variable=self.widget_variable[name+m_d_f])
                        self.widget_object[name+m_d_f+self.modes[s_m]].bind(
                            '<ButtonRelease-1>', self.tog)
                        self.widget_object[name+m_d_f+self.modes[s_m]].icombut = name+m_d_f
                        self.widget_object[name+m_d_f+self.modes[s_m]].command = hexstring
                        self.widget_object[name+m_d_f+self.modes[s_m]].hardvalue = self.modes[s_m]
                        self.widget_object[name+m_d_f+self.modes[s_m]].type = widg_type
                        self.widget_object[name+m_d_f+self.modes[s_m]].grid(
                            row=gridloc[m_d_f+str(int(self.modes[s_m]))][0],
                            column=gridloc[m_d_f+str(int(self.modes[s_m]))][1])
                        mdf_row += 1
                elif m_d_f == 'd':
                    mdf_row = 1
                    self.widget_variable[name+m_d_f] = tkinter.StringVar()
                    self.last_polled_value[name+m_d_f] = tkinter.StringVar()
                    self.widget_object[name+m_d_f] = tkinter.Radiobutton(
                        self.widget_object[name],
                        text='DATA',
                        padx=0,
                        pady=0,
                        width=width,
                        selectcolor='#aaffaa',
                        indicator='no',
                        value='01',
                        variable=self.widget_variable[name+m_d_f])
                    self.widget_object[name+m_d_f].bind('<ButtonRelease-1>', self.tog)
                    self.widget_object[name+m_d_f].icombut = name+m_d_f
                    self.widget_object[name+m_d_f].command = hexstring
                    self.widget_object[name+m_d_f].hardvalue = '01'
                    self.widget_object[name+m_d_f].type = widg_type
                    self.widget_object[name+m_d_f].grid(
                        row=gridloc[m_d_f+str(mdf_row)][0], column=gridloc[m_d_f+str(mdf_row)][1])
                    mdf_row += 1
                elif m_d_f == 'f':
                    mdf_row = 1
                    self.widget_variable[name+m_d_f] = tkinter.StringVar()
                    self.last_polled_value[name+m_d_f] = tkinter.StringVar()
                    for n_f in '123':
                        self.widget_object[name+m_d_f+n_f] = tkinter.Radiobutton(
                            self.widget_object[name],
                            text='FIL'+n_f,
                            padx=0,
                            pady=0,
                            width=width,
                            selectcolor='#aaffaa',
                            indicator='no',
                            value='0'+str(n_f),
                            variable=self.widget_variable[name+m_d_f])
                        self.widget_object[name+m_d_f+n_f].bind('<ButtonRelease-1>', self.tog)
                        self.widget_object[name+m_d_f+n_f].icombut = name+m_d_f
                        self.widget_object[name+m_d_f+n_f].command = hexstring
                        self.widget_object[name+m_d_f+n_f].hardvalue = '0'+str(n_f)
                        self.widget_object[name+m_d_f+n_f].type = widg_type
                        self.widget_object[name+m_d_f+n_f].grid(
                            row=gridloc[m_d_f+str(mdf_row)][0],
                            column=gridloc[m_d_f+str(mdf_row)][1])
                        mdf_row += 1

        elif widg_type == 'ScaleFF':
            self.widget_variable[name] = tkinter.StringVar()
            self.last_polled_value[name] = tkinter.StringVar()
            lowrange = list(values)[0]
            highrange = list(values)[-1]
            self.widget_object[name] = FlatScale(
                self.widget_object[win],
                title,
                4,
                from_=lowrange,
                to=highrange,
                resolution=slider_res,
                length=165,
                showvalue=0,
                orient=tkinter.HORIZONTAL,
                variable=self.widget_variable[name])
            self.widget_object[name].bind(
                '<ButtonPress-4>', lambda event, w=1: self.wheel(event, w))
            self.widget_object[name].bind(
                '<ButtonPress-5>', lambda event, w=-1: self.wheel(event, w))
            self.widget_object[name].bind(
                '<ButtonRelease-1>', self.slider)
            self.widget_object[name].bind(
                '<ButtonPress-1>', self.slideractive)
            self.widget_object[name].grid(
                row=rrow, column=ccol,
                rowspan=rrowspan, columnspan=ccolspan,
                sticky=tkinter.E)
            self.widget_object[name].bias = bias
            self.widget_object[name].values = values

        elif widg_type == 'Scale0255':
            self.widget_variable[name] = tkinter.StringVar()
            self.last_polled_value[name] = tkinter.StringVar()
            lowrange = list(values)[0]
            highrange = list(values)[-1]
            self.widget_object[name] = FlatScale(
                self.widget_object[win],
                title,
                4,
                from_=lowrange,
                to=highrange,
                resolution=slider_res,
                length=165,
                showvalue=0,
                orient=tkinter.HORIZONTAL,
                variable=self.widget_variable[name])
            self.widget_object[name].bind(
                '<ButtonPress-4>', lambda event, w=1: self.wheel(event, w))
            self.widget_object[name].bind(
                '<ButtonPress-5>', lambda event, w=-1: self.wheel(event, w))
            self.widget_object[name].bind(
                '<ButtonRelease-1>', self.slider)
            self.widget_object[name].bind(
                '<ButtonPress-1>', self.slideractive)
            self.widget_object[name].grid(row=rrow, column=ccol,
                                          rowspan=rrowspan, columnspan=ccolspan,
                                          sticky=tkinter.E)
            self.widget_object[name].bias = bias
            self.widget_object[name].values = values

        elif widg_type == 'Progressbar':
            self.widget_variable[name] = tkinter.StringVar()
            self.last_polled_value[name] = tkinter.StringVar()
            lowrange = list(values)[0]
            highrange = list(values)[-1]
            self.widget_object[name] = tkinter.ttk.Progressbar(
                self.widget_object[win],
                length=251,
                maximum=highrange,
                orient=tkinter.HORIZONTAL,
                variable=self.widget_variable[name])
            self.widget_object[name].grid(
                row=rrow, column=ccol,
                rowspan=rrowspan, columnspan=ccolspan,
                padx=0, pady=0, ipadx=0, ipady=0)
            self.widget_object[name].bias = bias
            self.widget_object[name].values = values

        elif widg_type == 'RadiobuttonMulti':
            #for multi, create button for each value, e.g. a 00 button, a 01 button, a 02 button..
            self.widget_variable[name] = tkinter.StringVar()
            self.last_polled_value[name] = tkinter.StringVar()
            self.widget_object[name] = tkinter.Frame(self.widget_object[win])
            self.widget_object[name].grid(
                row=rrow, column=ccol,
                rowspan=rrowspan, columnspan=ccolspan)
            w_col = 1
            #if it has a title make a label
            if title != '':
                self.widget_object[name+'label'] = tkinter.Label(
                    self.widget_object[name], text=title)
                self.widget_object[name+'label'].grid(row=1, column=w_col)
                w_col = w_col+1

            for v_l in values:
                self.widget_object[name+str(values[v_l])] = tkinter.Radiobutton(
                    self.widget_object[name],
                    text=v_l,
                    padx=0,
                    pady=0,
                    width=width,
                    selectcolor='#aaffaa',
                    indicator='no',
                    value=values[v_l],
                    variable=self.widget_variable[name])
                self.widget_object[name+str(values[v_l])].bind('<ButtonRelease-1>', self.tog)
                self.widget_object[name+str(values[v_l])].icombut = name
                self.widget_object[name+str(values[v_l])].command = hexstring
                self.widget_object[name+str(values[v_l])].hardvalue = values[v_l]
                self.widget_object[name+str(values[v_l])].type = widg_type
                self.widget_object[name+str(values[v_l])].grid(row=1, column=w_col)
                w_col = w_col+1

        elif widg_type == 'RadiobuttonTog':
            #wid = 9
            #if win == 'vfo':
            #    wid = 4
            for v_l in values:
                if values[v_l] == values[list(values)[-1]]:
                    self.widget_variable[name] = tkinter.StringVar()
                    self.widget_variable[name].set(values[list(values)[0]])
                    self.last_polled_value[name] = tkinter.StringVar()
                    self.last_polled_value[name].set(values[list(values)[0]])
                    self.widget_object[name] = tkinter.Radiobutton(
                        self.widget_object[win],
                        text=title,
                        padx=0,
                        pady=0,
                        width=width,
                        selectcolor='#aaffaa',
                        indicator='no',
                        value=values[list(values)[-1]],
                        variable=self.widget_variable[name])
                    self.widget_object[name].bind('<ButtonRelease-1>', self.tog)
                    self.widget_object[name].grid(row=rrow, column=ccol,
                                                  rowspan=rrowspan, columnspan=ccolspan)
                    self.widget_object[name].values = values
                    self.widget_object[name].hardvalue = values[v_l]
        else:
            print("NO WIDGET SECTION FOR "+widg_type)

        if asciimsg != '':
            CreateToolTip(self.widget_object[name], asciimsg)
        self.widget_object[name].icombut = name
        self.widget_object[name].command = hexstring
        self.widget_object[name].type = widg_type

    def build_scope(self,*args):
        """ puts scope on """
        self.scope_canvas=tkinter.Canvas(self.scopewin,width=475, height=160, background='#000000')
        self.waterfall_canvas=tkinter.Canvas(self.scopewin,width=475, height=self.wafa_bot, background='#000000')
        scopemsg="Scope: Click to go to that signal.  Right click to do the same with rouding to one kHz."
        self.scope_canvas_tt=CreateToolTip(self.scope_canvas, scopemsg)
        self.waterfall_canvas_tt=CreateToolTip(self.scope_canvas, scopemsg)
        self.scope_canvas.grid(row=2,column=1,columnspan=7)
        self.waterfall_canvas.grid(row=3,column=1,columnspan=7)

#        self.scope_canvas.bind("<MouseWheel>", scopewheelms)
#        self.scope_canvas.bind("<ButtonPress-4>", lambda event,a=239: scopewheel(event,a))
#        self.scope_canvas.bind("<ButtonPress-5>", lambda event,a=236.1: scopewheel(event,a)) # yes 237.2 is weird
        self.scope_canvas.bind("<Button-1>", scopeclick)
        self.scope_canvas.bind("<Button-3>", scopeclickround)

#        self.waterfall_canvas.bind("<MouseWheel>", scopewheelms)
#        self.waterfall_canvas.bind("<ButtonPress-4>", lambda event,a=239: scopewheel(event,a))
#        self.waterfall_canvas.bind("<ButtonPress-5>", lambda event,a=236.1: scopewheel(event,a)) # yes 237.2 is weird
        self.waterfall_canvas.bind("<Button-1>", scopeclick)
        self.waterfall_canvas.bind("<Button-3>", scopeclickround)

        #self.scopewin.bind("<Escape>", hide_scope)
        self.scopewin.protocol("WM_DELETE_WINDOW", hide_scope)
        self.scopewin.title('PyC-7300 Scope')
        # make empty lists
        self.wafa_pix={}
        for y in range(0,self.wafa_bot): # range means 0 to wafa_bot-1
            self.wafa_pix[str(y)]={}
        for x in range(0,475): # range means 0 to 474
            self.peaks[x]=[]
            if (x) % 47.5 < 1.0:
                self.grid_line[x] = self.scope_canvas.create_line((x,0,x,160),fill='#aaaaaa')
            phill='black'
            for y in range(0,self.wafa_bot): # range means 0 to wafa_bot-1
                self.wafa_pix[str(y)][x]=ICOM.waterfall_canvas.create_line( x, y, x+1, y, fill=phill, tags="t"+str(y))

        for x in range(0,475): # range means 0 to 474
            if x == 0:
                self.scope_peak_line[x]=self.scope_canvas.create_line((x,160,x,160),fill=self.scope_color['scope_peak_color'])
            else:
                self.scope_peak_line[x]=self.scope_canvas.create_line((x-1,160,x,160),fill=self.scope_color['scope_peak_color'])

        for x in range(0,475):
            if x == 0:
                self.scope_fill_line[x]=self.scope_canvas.create_line((x,160,x,160),fill=self.scope_color['scope_fill_color'])
            else:
                self.scope_fill_line[x]=self.scope_canvas.create_line((x,160,x,160),fill=self.scope_color['scope_fill_color'])

        for x in range(0,475):
            if x == 0:
                self.scope_spectrum_line[x]=self.scope_canvas.create_line((x,160,x,160),fill=self.scope_color['scope_line_color'])
            else:
                self.scope_spectrum_line[x]=self.scope_canvas.create_line((x-1,160,x,160),fill=self.scope_color['scope_line_color'])

        self.scope_oob_msg = self.scope_canvas.create_text((233,100),text="SCOPE OUT OF RANGE",fill='yellow')

        # tx/rx last so they're on top
        self.scope_transmit_freq=self.scope_canvas.create_line((238,0,238,160),fill='red')
        self.scope_receive_freq=self.scope_canvas.create_line((238,0,238,160),fill='green')
    
        X_SCOPEWIDTH = [ 2500, 5000, 10000, 25000, 50000, 100000, 250000, 500000 ]
        X_SCOPEEDGE = [ '01', '02', '03' ]
        X_SCOPEMULT = [ 'x1', 'x2', 'x4', 'x8' ]
    
        X_OFF_ON = collections.OrderedDict([('Off', b'\x00'), ('On', b'\x01')])
    
    
        self.makebutt(
            'scope_c_or_f', b'\x27\x14\x00', 'RadiobuttonTog', X_OFF_ON, 1,
            self.poll_scope_mask, 'Scope', 21, 3, 1, 1, 'Center', 0, 1, 9,
            "Scope:\r\rCentered or Fixed.")
    
        self.makebutt(
            'scope_width', b'\x27\x15', 'LabelCombobox', X_SCOPEWIDTH, 6,
            self.do_not_poll_mask, 'Scope', 21, 4, 1, 1, 'Width', 0, 1, 6,
            "Scope:\r\rWidth in Hz.")

        self.makebutt(
            'scope_edge', b'\x27\x16\x00', 'LabelCombobox', X_SCOPEEDGE, 1,
            self.poll_scope_mask, 'Scope', 21, 5, 1, 1, 'Edges', 0, 1, 6,
            "Scope:\r\rEdge Set from Radio.")

        self.makebutt(
            'scope_mult', b'scope_mult', 'LabelCombobox', X_SCOPEMULT, 0,
            self.do_not_poll_mask, 'Scope', 21, 8, 1, 1, 'Mult', 0, 1, 3,
            "Scope:\r\rMultiplier.")
    
        self.makebutt(
            'scopedata', b'\x27\x00', 'Software', {}, 500,
            self.do_not_poll_mask, 'Scope', 1, 9, 1, 1, 'Scope', 0, 1, 10,
            "Scope:\r\rThis is some experimental-ass bullshit here.")

        self.makebutt(
            'scopesenddata', b'\x27\x11', 'Software', {}, 500,
            self.do_not_poll_mask, 'Scope', 1, 9, 1, 1, 'Scope', 0, 1, 10,
            "Scope:\r\rThis is some experimental-ass bullshit here.")

        self.makebutt(
            'echo_on_off', b'\x1a\x05\x00\x75', 'Software', {}, 1,
            self.do_not_poll_mask, '', 1, 9, 1, 1, '', 0, 1, 10,
            "Scope:\r\rThis is some experimental-ass bullshit here.")
        self.makebutt(
            'transceive_on_off', b'\x1a\x05\x00\x71', 'Software', {}, 1,
            self.do_not_poll_mask, '', 1, 9, 1, 1, '', 0, 1, 10,
            "Scope:\r\rThis is some experimental-ass bullshit here.")

        self.scope_bot_lbl=tkinter.StringVar()
        self.scope_top_lbl=tkinter.StringVar()
        self.scope_bot_lbl.set("Bot: ")
        self.scope_top_lbl.set("Top: ")


        self.makebutt(
            'scope_bot_lbl', b'scope_bot_lbl', 'Label', {}, 0,
            self.do_not_poll_mask, 'Scope', 21, 6, 1, 1, self.scope_bot_lbl, 0, 1, 16,
            "Bottom:\r\rBottom of scale." )

        self.makebutt(
            'scope_top_lbl', b'scope_top_lbl', 'Label', {}, 0,
            self.do_not_poll_mask, 'Scope', 21, 7, 1, 1, self.scope_top_lbl, 0, 1, 16,
            "Top:\r\rTop of scale." )
    
        self.scopewin.withdraw()


###############end of RIG CLASS

#def ErrHan(er):
#    print(type(er))
#    print(er.args)
#    print(er)

def handle_escape_key(*args):
    """ user hits escape key """
    # pylint: disable=W0613
    if root.IN_ENTRY:
        root.focus()
        root.IN_ENTRY = False
        pollvfo()
        return
    root.after(10, quit_prog)

def restart_prog(*args):
    """ restart program """
    # pylint: disable=W0613
    CO.quitq.put('QUIT')
    #for c_p in CO.procs:
    #    c_p.terminate()
    #    c_p.join()
    argz = list(sys.argv)
    argz.insert(0, sys.executable)
    if os.name == 'nt':
        argz = ["\"%s\"" % a_g for a_g in argz]
    os.execv(sys.executable, argz)

def quit_prog(power=False,*args):
    """ quit the program w/o affecting radio """
    # pylint: disable=W0613
    if config.config_value['after_echo'] == 'On':
        CO.send_direct(ICOM.send_preamble_bin + b'\x1a\x05\x00\x75\x01' + ICOM.suffix_bin)
    if config.config_value['after_echo'] == 'Off':
        CO.send_direct(ICOM.send_preamble_bin + b'\x1a\x05\x00\x75\x00' + ICOM.suffix_bin)
    if config.config_value['after_transceive'] == 'Off':
        CO.send_direct(ICOM.send_preamble_bin + b'\x1a\x05\x00\x71\x00' + ICOM.suffix_bin)
    if config.config_value['after_transceive'] == 'On':
        CO.send_direct(ICOM.send_preamble_bin + b'\x1a\x05\x00\x71\x01' + ICOM.suffix_bin)
    if power:
        CO.send_direct(ICOM.send_preamble_bin + b'\x18\x00' + ICOM.suffix_bin)
        # keep these receivecycles
        receivecycle()
        receivecycle()
        time.sleep(.250)
    if os.name == 'posix':
        termios.tcsetattr(CO.ser,termios.TCSANOW,CO.oldattr)

    CO.quitq.put('QUIT')
    config.write_cfg()
    sys.exit()

def pollall():
    """ poll all masks """
    # called by power on and refresh
    poll_by_type(ICOM.poll_vfos_mask
                 +ICOM.poll_mem_mask
                 +ICOM.poll_keyer_mask
                 +ICOM.poll_scope_mask
                 +ICOM.poll_controls_mask
                 +ICOM.poll_meters_mask)
def pollsplash():
    """ poll stuff when starting the program except memories"""
    # called when starting program
    poll_by_type(ICOM.poll_vfos_mask
                 +ICOM.poll_keyer_mask
                 +ICOM.poll_scope_mask
                 +ICOM.poll_controls_mask
                 +ICOM.poll_meters_mask)


def pollvfo():
    """ poll vfo mask """
    poll_by_type(ICOM.poll_vfos_mask)

def pollmem():
    """ poll mem mask """
    # called by uneditkeyer, tog(rename_mem), tog(clear_mem), tog(erase_mem)
    poll_by_type(ICOM.poll_mem_mask)

#def pollkeyer():
#    """ poll mem mask """
#    poll_by_type(ICOM.poll_keyer_mask)

#def pollcontrol():
#    """ poll controls mask """
#    poll_by_type(ICOM.poll_controls_mask)

#def pollmeter():
#    """ poll meter mask """
#    poll_by_type(ICOM.poll_meters_mask)

def poll_by_type(items=255):
    """ poll specific mask as directed """
    for p_t in ICOM.poll_type:
        if ICOM.poll_type[p_t] & items > 0:
            if ICOM.poll_type[p_t] == ICOM.poll_mem_mask:
                # THIS IS FOR POPULATING THE cw_keyer AND poll_mem_mask ONLY
                if p_t[0:5] == 'keyer' and len(p_t) > 10:
                    #CO.queue_command(p_t)
                    CO.send_direct_command(p_t)
                elif p_t[0:6] == 'mem_ch' and len(p_t) > 6:
                    mm_b = ICOM.widget_object['set_mem_modebox'].get(int(p_t[6:10])-1)
                    if mm_b == " ":
                        #CO.queue_command(p_t)
                        CO.send_direct_command(p_t)
                else:
                    #CO.queue_command(p_t)
                    CO.send_direct_command(p_t)
            else:
                #CO.queue_command(p_t)
                CO.send_direct_command(p_t)


def populate_memch(win, returnval):
    """ populate memory channel """
    thing = returnval[2:].hex()
    slot = returnval[1:2].hex()
    islot = int(slot)-1
    if thing != 'fffd':
        tmp = RadioMemory(thing)
        ICOM.memory_channel[islot] = tmp
        win.delete(islot)
        win.insert(islot,
                   slot+": "+tmp.minimemchformat.format(tmp.rx_frequency_mhz,
                                                        tmp.rx_mode,
                                                        tmp.nameraw.decode()))

    if thing == 'fffd':
        try:
            del ICOM.memory_channel[islot]
        except:
            pass
        win.delete(islot)
        win.insert(islot, slot+": "+"(radio memory not set)")

    q=win.bbox(islot)
    win.selection_set(islot)
    if q is not None:
        # simulate a button release on that slot so that it's highlit
        #win.event_generate('<ButtonPress-1>',x=q[0],y=q[1],state=16+256)
        win.event_generate('<ButtonRelease-1>',x=q[0],y=q[1],state=16+256)

#def cyclicalpoll():
#    """ poll cyclically """
#
#    # ONE
#    # every cycle we get a meter
#    CO.queue_command('s_meter')
#
#    # TWO
#    # get next meter in line each time
#    CO.queue_command(ICOM.poll_list[ICOM.poll_meters_mask].data)
#    ICOM.poll_list[ICOM.poll_meters_mask] = ICOM.poll_list[ICOM.poll_meters_mask].next
#
#    # THREE
#    # get one of the vfo each time
#    CO.queue_command(ICOM.poll_list[ICOM.poll_vfos_mask].data)
#    ICOM.poll_list[ICOM.poll_vfos_mask] = ICOM.poll_list[ICOM.poll_vfos_mask].next
#
#    # FOUR
#    # if SCOPE appears to exist
#    if ICOM.poll_list[ICOM.poll_scope_mask] is not None:
#        # if SCOPE appears to exist
#        if ICOM.scopewin.winfo_ismapped():
#            CO.queue_command(ICOM.poll_list[ICOM.poll_scope_mask].data)
#            ICOM.poll_list[ICOM.poll_scope_mask] = ICOM.poll_list[ICOM.poll_scope_mask].next
#            #return
#
#    # FIVE
#    # get one control each time
#    CO.queue_command(ICOM.poll_list[ICOM.poll_controls_mask].data)
#    ICOM.poll_list[ICOM.poll_controls_mask] = ICOM.poll_list[ICOM.poll_controls_mask].next
#
#    # SIX
#    # every complete VFO cycle we get one keyer reading and go thru mems and update
#    if ICOM.poll_list[ICOM.poll_vfos_mask] == ICOM.poll_first[ICOM.poll_vfos_mask]:
#        CO.queue_command(ICOM.poll_list[ICOM.poll_keyer_mask].data)
#        ICOM.poll_list[ICOM.poll_keyer_mask] = ICOM.poll_list[ICOM.poll_keyer_mask].next
#
#        #if ICOM.poll_list[ICOM.poll_controls_mask] == ICOM.poll_first[ICOM.poll_controls_mask]:
#        for i, lbent in enumerate(ICOM.widget_object['set_mem_modebox'].get(0,tkinter.END)):
#            if lbent == " ":
#                mcn=('0000'+str(i+1))[-4:]
#                CO.queue_command('mem_ch'+mcn)

def pollnextitem():
    #CO.queue_now_command('s_meter')
    CO.send_direct_command('s_meter')
    #for x in {1,2,4,8,16,32}:
    # send five commands...
    for x in {1,2,4,8,16}:
        CO.send_direct_command(ICOM.poll_list[x].data)
        ##if x <= 4:
        ##    #CO.queue_now_command(ICOM.poll_list[x].data)
        ##    CO.send_direct_command(ICOM.poll_list[x].data)
        ##else:
        ##    #CO.queue_command(ICOM.poll_list[x].data)
        ##    CO.send_direct_command(ICOM.poll_list[x].data)

        ICOM.poll_list[x] = ICOM.poll_list[x].next
    # get blank memories but only five at a time...
    mm = 1
    for i, lbent in enumerate(ICOM.widget_object['set_mem_modebox'].get(0,tkinter.END)):
        if lbent == " ":
            if mm < 3:
                mcn=('0000'+str(i+1))[-4:]
                #CO.queue_command('mem_ch'+mcn)
                CO.send_direct_command('mem_ch'+mcn)
            mm = mm + 1


def receivecycle():
    """ run one poll cycle and then receive til queue empty """
    #print("b",flush=True,end='')
    CO.direct_receive()
    #print("a",flush=True,end='')
    CO.direct_receive()
    # get sump'n from the socket from the logger
    logline=loggersock.non_blocking_rx_until(b'\xfd')
    qsyline=qsysock.non_blocking_rx_until(b'\x0d')
    #n3fjpline=n3fjpsock.non_blocking_rx_until(b'\x0d')
    #if n3fjpline is not None:
    #    print("n3fjp: "+str(n3fjpline))
    if qsyline is not None:
        ivalue=int(float(qsyline.decode())*1000)
        qsy = "{:010d}".format(ivalue)
        # bytes.fromhex is OK here
        bqsy = ICOM.send_preamble_bin + \
               ICOM.widget_object['this_vfo_freq'].command + \
               bytes.fromhex(qsy)[::-1] + \
               ICOM.suffix_bin

        CO.send_direct(bqsy)
    if logline is not None:
        CO.send_direct(logline)
    if CO.recvq.qsize() > 0:
        cg = CO.recvq.get(False)
        if cg is not None:
            if cg[0:5] in ( \
                ICOM.receive_preamble_bin+b'\x03', \
                ICOM.receive_preamble_bin+b'\x04', \
                ICOM.receive_preamble_bin+b'\x05', \
                ICOM.receive_preamble_bin+b'\x06'  \
                ):
                loggersock.sxdata(cg)
        ICOM.run_command(cg)
    else:
        pollnextitem()

    if os.name == 'nt':
        # posix can update individual widgets evidently and windows can't 
        root.update()


# create config instance
config = CONFIG()
config.read_cfg()

# **************************************************************
# END OF USER VAR SECTION
# **************************************************************

CO = COMM()
loggersock=Socky("",int(config.config_value['loggerport']),True)
qsysock=Socky("",int(config.config_value['qsyport']),True)
#n3fjpsock=Socky("192.168.42.152",1100,False)

# this line is so winduhz will work
if __name__ == '__main__':

    root = tkinter.Tk()
    ICOM = IC7300()

    C_TRIGGERCHAN = collections.OrderedDict([
        ('1', b'\x01'), ('2', b'\x02'), ('3', b'\x03'), ('4', b'\x04'),
        ('5', b'\x05'), ('6', b'\x06'), ('7', b'\x07'), ('8', b'\x08')])
    C_KEYERSLOTS = collections.OrderedDict([
        ('M1', b'\x01'), ('M2', b'\x02'), ('M3', b'\x03'), ('M4', b'\x04'),
        ('M5', b'\x05'), ('M6', b'\x06'), ('M7', b'\x07'), ('M8', b'\x08')])
    C_VKEYERSLOTS = collections.OrderedDict([
        ('T1', b'\x01'), ('T2', b'\x02'), ('T3', b'\x03'), ('T4', b'\x04'),
        ('T5', b'\x05'), ('T6', b'\x06'), ('T7', b'\x07'), ('T8', b'\x08')])
    C_BREAKIN = collections.OrderedDict([('Off', b'\x00'), ('Semi', b'\x01'), ('Full', b'\x02')])
    C_KEYTYPE = collections.OrderedDict([('SK', b'\x00'), ('"Bug"', b'\x01'), ('Paddles', b'\x02')])
    C_PREAMP = collections.OrderedDict([('Off', b'\x00'), ('1', b'\x01'), ('2', b'\x02')])
    C_AGC = collections.OrderedDict([('Fast', b'\x01'), ('Med', b'\x02'), ('Slow', b'\x03')])
    C_PADPOL = collections.OrderedDict([('Norm', b'\x00'), ('Rev', b'\x01')])
    C_SCOPEWIDTH = [ 2500, 5000, 10000, 25000, 50000, 100000, 250000, 500000 ]
    C_OFF_ON = collections.OrderedDict([('Off', b'\x00'), ('On', b'\x01')])
    C_OFF_ON_ATT = collections.OrderedDict([('Off', b'\x00'), ('On', b'\x20')])
    C_PTT = collections.OrderedDict([('RX', b'\x00'), ('TX', b'\x01')])
    C_FA_CODE = {int('fa', 16), ICOM.rig_id_bin[0]}
    C_PITCH = list(range(300, 901))
    C_WPM = list(range(6, 49))
    C_LEV_0_100 = list(range(0, 101))
    C_LEV_1_100 = list(range(1, 101))
    C_LEV_1_10 = list(range(1, 11))
    C_LEV_0_15 = list(range(0, 16))
    C_LEV_0_255 = list(range(0, 256))
    C_LEV_0_120 = list(range(0, 121))
    C_LEV_0_241 = list(range(0, 242))
    C_LEV_0_213 = list(range(0, 214))
    C_LEV_1_20 = list(range(1, 22))
    C_LEV_28_45 = list(range(28, 46))
    C_RIT = list(range(-9999, 9999))
    C_CONTEST = list(range(1, 10000))
    C_SHARP = collections.OrderedDict([('Sharp', b'\x00'), ('Soft', b'\x01')])
    C_SSBWID = collections.OrderedDict([('Wide', b'\x00'), ('Mid', b'\x01'), ('Nar', b'\x02')])
    C_SPEED = ['CPU Saver', 'Moderate', 'Fast']
    C_THEME = ['Medium', 'Light', 'Heathkit', 'Kenwood', 'HotDog Stand', 'Go Big Blue']
    C_VOXVD = collections.OrderedDict([('Off', b'\x00'), ('Short', b'\x01'),
                                       ('Mid', b'\x02'), ('Long', b'\x03')])


####################################################################################################
    ICOM.makebutt(
        'keyer_send', b'\x1a\x02', 'ButtonMulti', C_KEYERSLOTS, 71,
        ICOM.poll_keyer_mask, 'CW Keyer', 1, 1, 1, 5, '', 0, 1, 10)
    ICOM.makebutt(
        'contestnums', b'\x1a\x05\x01\x55', 'LabelCombobox', {}, 1,
        ICOM.poll_controls_mask, 'CW Keyer', 2, 1, 1, 1, 'Serial Style', 0, 1, 8,
        "CW Contest Serial Number Style:\r\r" \
        +"Normal, ANO, ANT, 1NO, 1NT for 1, 9, and zero.  Drives me batty.")
    ICOM.makebutt(
        'contest_num', b'\x1a\x05\x01\x57', 'SmallVFO', C_CONTEST, 2,
        ICOM.poll_controls_mask, 'CW Keyer', 2, 2, 1, 1, '', 0, 1, 6,
        "CW Contest Serial Number:\r\r" \
        +"This is the number in the radio. " \
        +"The chosen channel has to match the entry with the asterisk.")
    ICOM.makebutt(
        'trigger_chan', b'\x1a\x05\x01\x56', 'RadiobuttonMulti', C_TRIGGERCHAN, 1,
        ICOM.poll_controls_mask, 'CW Keyer', 2, 3, 1, 3, '', 0, 1, 1,
        "CW Contest Channel:\r\r" \
        +"Which channel is the contest keyer serial number trigger.")
    ICOM.makebutt(
        'freeform_send', b'\x17', 'LabelEntry', '', 0,
        ICOM.do_not_poll_mask, 'CW Keyer', 3, 1, 1, 3, 'Send CW', 0, 1, 30,
        "Send CW:\r\r" \
        +"Click the box, type stuff in, hit enter.  Cuss words are not filtered out, so careful!")
    ICOM.makebutt(
        'cwstop', b'\x17\xff', 'Button', '', 0,
        ICOM.do_not_poll_mask, 'CW Keyer', 3, 3, 1, 1, 'Stop!', 0, 1, 4,
        "Stop!\r\r" \
        +"If you put a big string out or you need to stop keying, hit this. You can also touch " \
        +"your regular CW key and the radio will stop.")
    ICOM.makebutt(
        'edkeyer', b'edkeyer', 'Button', '', 0,
        ICOM.do_not_poll_mask, 'CW Keyer', 3, 4, 1, 1, 'Edit', 0, 1, 4,
        "Edit Keyer:\r\r" \
        +"Lets you edit the CW keyer in the radio.")
    ICOM.makebutt(
        'level_wpm', b'\x14\x0c', 'Scale0255', C_WPM, 2,
        ICOM.poll_controls_mask, 'CW Keyer', 4, 1, 1, 3, 'CW WPM', 0, 1, 50,
        "CW WPM:\r\r" \
        +"Words per minute for the built-in keyer.")
    ICOM.makebutt(
        'paddlepol', b'\x1a\x05\x01\x63', 'RadiobuttonTog', C_PADPOL, 1,
        ICOM.poll_controls_mask, 'CW Keyer', 4, 4, 1, 1, 'Rev', 0, 1, 4,
        "Paddle Polarity:\r\r" \
        +"Toggle between righty and lefty when using keyer paddles.")

    ICOM.makebutt(
        'vkeyer_send', b'\x28\x00', 'ButtonMulti', C_VKEYERSLOTS, 71,
        ICOM.do_not_poll_mask, 'Voice Keyer', 1, 1, 1, 1, '', 0, 1, 10,
        "Voice Keyer:\r\rRig's built-in voice memory keyer slots. " \
        +"This will transmit the contents. Sadly, the radio has no " \
        +"CI-V provision to retrieve the names of the slots and display " \
        +"them in the program.")

    ############################ cw frame
    ICOM.makebutt(
        'key_type', b'\x1a\x05\x01\x64', 'RadiobuttonMulti', C_KEYTYPE, 1,
        ICOM.poll_controls_mask, 'CW', 1, 1, 1, 1, 'Key', 0, 1, 8,
        "Key Type:\r\r" \
        +"SK or Bug.\r" \
        +"Bug\": Use keyer paddle like a bug.\r" \
        +"Paddles: Full electronic keying.")
    ICOM.makebutt(
        'side_tone_limit', b'\x1a\x05\x01\x59', 'RadiobuttonTog', C_OFF_ON, 1,
        ICOM.poll_controls_mask, 'CW', 1, 2, 1, 1, 'Side Tone Limit', 0, 1, 12,
        "CW Side Tone Limit:\r\rLimit to the same as regular volume.")
    ICOM.makebutt(
        'level_pitch', b'\x14\x09', 'Scale0255', C_PITCH, 2,
        ICOM.poll_controls_mask, 'CW', 3, 1, 1, 2, 'CW Pitch', 0, 5, 50,
        "CW Pitch:\r\r" \
        +"The frequency of the sidetone you hear, " \
        +"as well as the radio's filters matching it.")
    ICOM.makebutt(
        'dot_dash', b'\x1a\x05\x01\x61', 'ScaleFF', C_LEV_28_45, 1,
        ICOM.poll_controls_mask, 'CW', 4, 1, 1, 2, 'Dot:Dash', 0, 1, 1,
        "Dot-Dash ratio\r\r28 is 1:1:2.8\r30 is 1:1:3 (normal)\r45 is 1:1:4.5")
    ICOM.makebutt(
        'side_tone_level', b'\x1a\x05\x01\x58', 'Scale0255', C_LEV_0_100, 2,
        ICOM.poll_controls_mask, 'CW', 2, 1, 1, 2, 'Side Tone Level', 0, 1, 50,
        "CW Side Tone Level:\r\rVolume of the side tone.")

    ############################ cw/ssb frame
    ICOM.makebutt(
        'vox_on_off', b'\x16\x46', 'RadiobuttonTog', C_OFF_ON, 1,
        ICOM.poll_controls_mask, 'Break-In/VOX', 1, 2, 1, 1, 'VOX', 0, 1, 7,
        "VOX:\r\rOff, use PTT to transmit." \
        +"\rOn, start yapping to transmit.")
    ICOM.makebutt(
        'bkin_type', b'\x16\x47', 'RadiobuttonMulti', C_BREAKIN, 1,
        ICOM.poll_controls_mask, 'Break-In/VOX', 1, 1, 1, 1, 'Break-in/VOX', 0, 1, 7,
        "QSK:\r\rOff, no transmit." \
        +"\rSemi, relay stays engaged between letters." \
        +"\rFull, hear receive between dits, useless at high speed.")

    ############################ ssb frame
    ICOM.makebutt(
        'level_mic', b'\x14\x0b', 'Scale0255', C_LEV_0_100, 2,
        ICOM.poll_controls_mask, 'SSB', 1, 2, 1, 1, 'Mic', 0, 1, 50,
        "Mic Gain:\r\rRighty Loudy, Lefty Quiety." \
        +"\r\rIf you use your radio on 11 meters, turn it all " \
        +"the way right, good buddy.")
    ICOM.makebutt(
        'level_comp', b'\x14\x0e', 'Scale0255', C_LEV_0_100, 2,
        ICOM.poll_controls_mask, 'SSB', 2, 2, 1, 1, 'Comp', 0, 1, 50,
        "Compression Level:\r\rAudio compression for voice.")
    ICOM.makebutt(
        'vox_gain', b'\x14\x16', 'Scale0255', C_LEV_0_100, 2,
        ICOM.poll_controls_mask, 'SSB', 3, 2, 1, 1, 'VOX Gain', 0, 1, 50,
        "VOX Gain:\r\rIncreases sensitivity to voice.")
    ICOM.makebutt(
        'avox_gain', b'\x14\x17', 'Scale0255', C_LEV_0_100, 2,
        ICOM.poll_controls_mask, 'SSB', 4, 2, 1, 1, 'Anti-VOX', 0, 1, 50,
        "Anti VOX Gain:\r\rDecreases sensitivity to speakers, etc.")
    ICOM.makebutt(
        'vox_delay', b'\x1a\x05\x01\x91', 'ScaleFF', C_LEV_1_20, 1,
        ICOM.poll_controls_mask, 'SSB', 5, 2, 1, 1, 'VOX Delay', 1, 1, 50,
        "VOX Delay:\r\r1 is 0 seconds and 21 is 2.0 seconds." \
        +"\rHow long the transmitter stays keyed after you shut up.")
    ICOM.makebutt(
        'vox_vd', b'\x1a\x05\x01\x92', 'RadiobuttonMulti', C_VOXVD, 1,
        ICOM.poll_controls_mask, 'SSB', 6, 2, 1, 1, 'Voice Delay', 0, 1, 6,
        "VOX Voice Delay:\r\rAdjust to prevent cutting off your first words, etc.")
    ICOM.makebutt(
        'ssb_wid', b'\x16\x58', 'RadiobuttonMulti', C_SSBWID, 1,
        ICOM.poll_controls_mask, 'SSB', 7, 2, 1, 1, 'SSB Width', 0, 1, 8,
        "SSB Transmit Width:\r\rSwitch between Wide, Middle and Narrow.")
#    ICOM.makebutt(
#        'scope', b'\x27\x10', 'RadiobuttonTog', C_OFF_ON, 1,
#        ICOM.poll_controls_mask, 'SSB', 1, 1, 1, 1, 'Scope', 0, 1, 7,
#        "Scope:\r\rTurn Scope on/off on radio.")
    ICOM.makebutt(
        'comp_on_off', b'\x16\x44', 'RadiobuttonTog', C_OFF_ON, 1,
        ICOM.poll_controls_mask, 'SSB', 2, 1, 1, 1, 'Comp', 0, 1, 7,
        "Compression On/Off:\r\rTurn SSB voice compression on/off")
    ICOM.makebutt(
        'moni_on_off', b'\x16\x45', 'RadiobuttonTog', C_OFF_ON, 1,
        ICOM.poll_controls_mask, 'SSB', 8, 1, 1, 1, 'Monitor', 0, 1, 7,
        "Monitor On/Off:\r\rTurn on monitoring of audio on SSB.\r\r(May cause feedback)")
    ICOM.makebutt(
        'level_mon', b'\x14\x15', 'Scale0255', C_LEV_0_100, 2,
        ICOM.poll_controls_mask, 'SSB', 8, 2, 1, 1, 'Mon Lev', 0, 1, 7,
        "Monitor Level:\r\rAdjust the level of monitoring of audio on SSB.")



    ############################ mtr frame
    ICOM.makebutt(
        'swr_meter', b'\x15\x12', 'Progressbar', C_LEV_0_100, 2,
        ICOM.poll_meters_mask, 'Meters', 1, 1, 1, 10, 'SWR', 0, 1, 251,
        "SWR:\r\rAn approximation of the built-in SWR meter. " \
        +"Halfway is about 3:1, similar to the rig's built in meter.")
    ICOM.makebutt(
        'po_meter', b'\x15\x11', 'Progressbar', C_LEV_0_100, 2,
        ICOM.poll_meters_mask, 'Meters', 5, 1, 1, 10, 'PO', 0, 1, 251,
        "Power Out:\r\rAn approximation of the radio's power out meter.")
    ICOM.makebutt(
        'alc_meter', b'\x15\x13', 'Progressbar', C_LEV_0_120, 2,
        ICOM.poll_meters_mask, 'Meters', 4, 11, 1, 10, 'ALC', 0, 1, 251,
        "ALC:\r\rAn approximation of the built-in ALC meter.")
    ICOM.makebutt(
        's_meter', b'\x15\x02', 'Progressbar', C_LEV_0_241, 2,
        ICOM.poll_meters_mask, 'Meters', 8, 11, 1, 10, 'S', 0, 1, 251,
        "S-Meter:\r\rAn approximation of the S-meter. Halfway is about S-9.")
    ICOM.makebutt(
        'ovfb', b'ovfb', 'Label', C_FA_CODE, 0,
        ICOM.do_not_poll_mask, 'Meters', 9, 1, 1, 1, ICOM.overflow_indicator, 0, 1, 3,
        "Overflow:\r\rRed indicates RF overflow into your SDR." \
        +"\r\rTurn down RF gain or turn off P.Amp, or turn on Att to alleviate.")
    ICOM.makebutt(
        'datedisp', b'datedisp', 'Label', C_FA_CODE, 0,
        ICOM.do_not_poll_mask, 'Meters', 9, 2, 1, 7, ICOM.radio_date, 0, 1, 10,
        "Date from radio")
    ICOM.makebutt(
        'timedisp', b'timedisp', 'Label', C_FA_CODE, 0,
        ICOM.do_not_poll_mask, 'Meters', 9, 8, 1, 8, ICOM.radio_time, 0, 1, 12,
        "Time from radio")
    ICOM.makebutt(
        'callbrag', b'callbrag', 'Label', C_FA_CODE, 0,
        ICOM.do_not_poll_mask, 'Meters', 9, 16, 1, 4, ICOM.my_call_sign, 0, 1, 10,
        "Your callsign or message from radio")
    ICOM.makebutt(
        'qstat', b'qstat', 'Label', C_FA_CODE, 0,
        ICOM.do_not_poll_mask, 'Meters', 10, 1, 1, 19, ICOM.status_line, 0, 1, 26,
        "Your callsign or message from radio")


    ############################ tx frame
    ICOM.makebutt(
        'txind', b'\x1c\x00', 'RadiobuttonTog', C_PTT, 1,
        ICOM.poll_meters_mask, 'Transmit', 1, 1, 1, 1, 'TX', 0, 1, 10,
        "TX:\r\rOn when transmitting.\rYou can also press this for PTT.")
    ICOM.makebutt(
        'txmon', b'\x1c\x02', 'RadiobuttonTog', C_OFF_ON, 1,
        ICOM.poll_controls_mask, 'Transmit', 1, 2, 1, 1, 'MON TX', 0, 1, 10,
        "TX MON:\r\rWhile engaged, listen to the transmit frequency" \
        +"\r(i.e. when working split to hear the pile up instead of the DX")
    ICOM.makebutt(
        'tuner', b'\x1c\x01', 'RadiobuttonTog', C_OFF_ON, 1,
        ICOM.poll_controls_mask, 'Transmit', 1, 3, 1, 1, 'TUNER', 0, 1, 10,
        "TUNER:\r\rTurn the tuner on or off.")
    ICOM.makebutt(
        'tuner', b'\x1c\x01\x02', 'Button', C_OFF_ON, 1,
        ICOM.poll_controls_mask, 'Transmit', 1, 4, 1, 1, 'TUNE', 0, 1, 10,
        "TUNE:\r\rHit this to tune the antenna tuner.\rIt will transmit.")
    ICOM.makebutt(
        'level_txpwr', b'\x14\x0a', 'Scale0255', C_LEV_0_100, 2,
        ICOM.poll_controls_mask, 'Transmit', 2, 1, 1, 4, 'TX Power', 0, 1, 50,
        "Transmit power:\r\rZero to 100 in percent, not necessarily watts.")

    ############################ rx frame
    ICOM.makebutt(
        'nb_on_off', b'\x16\x22', 'RadiobuttonTog', C_OFF_ON, 1,
        ICOM.poll_controls_mask, 'Receive', 1, 1, 1, 1, 'NB', 0, 1, 10,
        "Noise Blanker: On or Off")
    ICOM.makebutt(
        'level_nb_lev', b'\x14\x12', 'Scale0255', C_LEV_0_100, 2,
        ICOM.poll_controls_mask, 'Receive', 1, 2, 1, 2, 'NB Lev', 0, 1, 50,
        "Noise Blanker Level:\r\rSee your Icom manual for a description." \
        +" Half way usually works well.")
    ICOM.makebutt(
        'level_nb_dep', b'\x1a\x05\x01\x89', 'ScaleFF', C_LEV_1_10, 1,
        ICOM.poll_controls_mask, 'Receive', 1, 4, 1, 2, 'NB Depth', 1, 1, 50,
        "Noise Blanker Depth:\r\rSee your Icom manual for a description." \
        +" Half way usually works well.")
    ICOM.makebutt(
        'level_nb_wid', b'\x1a\x05\x01\x90', 'Scale0255', C_LEV_1_100, 2,
        ICOM.poll_controls_mask, 'Receive', 1, 6, 1, 2, 'NB Width', 0, 1, 50,
        "Noise Blanker Width:\r\rSee your Icom manual for a description." \
        +" Half way usually works well.")

    ICOM.makebutt(
        'nr_on_off', b'\x16\x40', 'RadiobuttonTog', C_OFF_ON, 1,
        ICOM.poll_controls_mask, 'Receive', 2, 1, 1, 1, 'NR', 0, 1, 10,
        "Noise Reduction: On or Off\r\rWarning: Turning on NR with AGC time " \
        +"constant set to 0.0 can cause problems.")
    ICOM.makebutt(
        'level_nr', b'\x14\x06', 'Scale0255', C_LEV_0_15, 2,
        ICOM.poll_controls_mask, 'Receive', 2, 2, 1, 2, 'NR', 8, 1, 50,
        "Noise Reduction Level:\r\rSee your Icom manual for a description." \
        +"\rA little over half way usually works well, \rwith diminishing " \
        +"returns past that.")
    ICOM.makebutt(
        'level_if_inner', b'\x14\x07', 'Scale0255', C_LEV_0_100, 2,
        ICOM.poll_controls_mask, 'Receive', 2, 4, 1, 2, 'IF Inner', 0, 1, 50,
        "TWIN PBT Inner:\r\rSee your Icom manual for a description." \
        +"\rNormal position is 50.")
    ICOM.makebutt(
        'level_if_outer', b'\x14\x08', 'Scale0255', C_LEV_0_100, 2,
        ICOM.poll_controls_mask, 'Receive', 2, 6, 1, 2, 'IF Outer', 0, 1, 50,
        "TWIN PBT Outer:\r\rSee your Icom manual for a description." \
        +"\rNormal position is 50.")

    ICOM.makebutt(
        'ip_plus', b'\x16\x65', 'RadiobuttonTog', C_OFF_ON, 1,
        ICOM.poll_controls_mask, 'Receive', 3, 1, 1, 1, 'IP+', 0, 1, 10,
        "IP+: Does anyone know how this works?")
    ICOM.makebutt(
        'level_af', b'\x14\x01', 'Scale0255', C_LEV_0_100, 2,
        ICOM.poll_controls_mask, 'Receive', 3, 2, 1, 2, 'Vol', 0, 1, 50,
        "AF Gain:\r\rRighty loudy, lefty quiety.")
    ICOM.makebutt(
        'level_rf', b'\x14\x02', 'Scale0255', C_LEV_0_100, 2,
        ICOM.poll_controls_mask, 'Receive', 3, 4, 1, 2, 'RFG', 0, 1, 50,
        "RF Gain:\r\rMagical control that can make" \
        +"\rnoise reduction work even better by reducing it," \
        +"\respecially on bands 40 meters and below.")
    ICOM.makebutt(
        'level_sql', b'\x14\x03', 'Scale0255', C_LEV_0_100, 2,
        ICOM.poll_controls_mask, 'Receive', 3, 6, 1, 2, 'Squelch', 0, 1, 50,
        "Squelch:\r\rRightward silences radio unless signal is strong enough.")

    ICOM.makebutt(
        'anotch_on_off', b'\x16\x41', 'RadiobuttonTog', C_OFF_ON, 1,
        ICOM.poll_controls_mask, 'Receive', 4, 2, 1, 1, 'Auto Notch', 0, 1, 10,
        "Auto Notch:\r\rAutomatic notch filter.  Might filter desired signal.")
    ICOM.makebutt(
        'notch_on_off', b'\x16\x48', 'RadiobuttonTog', C_OFF_ON, 1,
        ICOM.poll_controls_mask, 'Receive', 4, 3, 1, 1, 'Notch', 0, 1, 10,
        "Notch Filter:\r\rOn or Off")
    ICOM.makebutt(
        'level_notch', b'\x14\x0d', 'Scale0255', C_LEV_0_100, 2,
        ICOM.poll_controls_mask, 'Receive', 4, 4, 1, 2, 'Notch', 0, 1, 50,
        "Notch Filter:\r\rUsually slightly off to one side or other " \
        +"of desired signal to block out QRM.")

    ICOM.makebutt(
        'att_on_off', b'\x11', 'RadiobuttonTog', C_OFF_ON_ATT, 1,
        ICOM.poll_controls_mask, 'Receive', 4, 6, 1, 1, 'Att', 0, 1, 10,
        "Attenuator 20dB:\r\rAttenuate signal by 20 decibels.  When on, P.Amp is off. " \
        +"Turning on P.Amp turns this off.")
    ICOM.makebutt(
        'preamp_type', b'\x16\x02', 'RadiobuttonMulti', C_PREAMP, 1,
        ICOM.poll_controls_mask, 'Receive', 4, 7, 1, 1, 'P.Amp', 0, 1, 4,
        "Preamp:\r\rMostly for high bands, boost receive level. " \
        +"When on, Attenuator is off. Turning on Attenuator turns this off.")

    ############################ agc frame
    ICOM.makebutt(
        'agc_type', b'\x16\x12', 'RadiobuttonMulti', C_AGC, 1,
        ICOM.poll_controls_mask, 'AGC', 1, 1, 1, 1, 'AGC', 0, 1, 5,
        "AGC Type:\r\rFast, Medium, or Slow." \
        +"\r\rYou can set these to any timing you want with" \
        +"\rthe AGC dropdown above, so they may as well\rhave called it 1, 2 and 3.")
    ICOM.makebutt(
        'agc_time', b'\x1a\x04', 'LabelCombobox', {}, 1,
        ICOM.poll_controls_mask, 'AGC', 2, 1, 1, 1, 'Time', 0, 1, 4,
        "AGC Timing:\r\rPull down list to pick your AGC timing." \
        +"\r\rWarning: Setting to 0 (Off) can cause strong signals to be extremely loud. " \
        +"Zero (off) may also not work well with NR on.")

    ############################ vfo frame
    ICOM.makebutt(
        'this_vfo_freq', b'\x25\x00', 'VFOSet', {}, 5,
        ICOM.poll_vfos_mask, 'Frequency', 1, 1, 3, 5, 'This VFO', 0, 1, 10,
        'Selected VFO:\r\rClick for entry or spin mouse wheel to change digits.')
    ICOM.makebutt(
        'that_vfo_freq', b'\x25\x01', 'VFOSet', {}, 5,
        ICOM.poll_vfos_mask, 'Frequency', 4, 1, 3, 5, 'That VFO', 0, 1, 10,
        'Unselected VFO:\r\rClick for entry or spin mouse wheel to change digits.')

    ICOM.makebutt(
        'this_vfo_mdf', b'\x26\x00', 'MDFSet', {}, 3,
        ICOM.poll_vfos_mask, 'Frequency', 1, 6, 1, 5, 'MDF', 0, 1, 6,
        "Selected Mode:\r\rChoose filter, mode and data.  Data not available in all modes.")
    ICOM.makebutt(
        'that_vfo_mdf', b'\x26\x01', 'MDFSet', {}, 3,
        ICOM.poll_vfos_mask, 'Frequency', 4, 6, 1, 5, 'MDF', 0, 1, 6,
        "Unselected Mode:\r\rChoose filter, mode and data.  Data not available in all modes.")

    ICOM.makebutt(
        'set_mem_modebox', b'\x08', 'ListBox', {}, 0,
        ICOM.do_not_poll_mask, 'Frequency', 7, 1, 6, 1, 'MEM', 0, 1, 10,
        "Rig's memories:\r\rMouse wheel scrolls box, " \
        +"double click jumps radio to memory.  Single click to do a save, erase, or rename on it.")

    ICOM.makebutt(
        'cur_rx_bw', b'\x1a\x03', 'LabelCombobox', {}, 1,
        ICOM.poll_controls_mask, 'Frequency', 8, 6, 1, 1, 'Wid', 0, 1, 5,
        "Receive bandwidth:\r\rChange bandwidth for current filter.")
    ICOM.makebutt(
        'filter_sharp', b'\x16\x56', 'RadiobuttonMulti', C_SHARP, 1,
        ICOM.poll_controls_mask, 'Frequency', 8, 7, 1, 2, '', 0, 1, 10,
        "Filter \"edges\":\r\rSwitch between sharp and soft edges to taste.")

    ICOM.makebutt(
        'rename_mem', b'\x0b', 'Button', {}, 0,
        ICOM.do_not_poll_mask, 'Frequency', 9, 6, 1, 1, 'Name Mem', 0, 1, 10,
        "Name Mem:\r\rAllows you to name a memory you just saved, " \
        +"\ror rename an already existing memory.\r\rYou made a backup, right?")
    ICOM.makebutt(
        'clear_mem', b'\x0b', 'Button', {}, 0,
        ICOM.do_not_poll_mask, 'Frequency', 9, 7, 1, 1, 'Erase Mem', 0, 1, 10,
        "Erase Mem:\r\rThis nukes a memory in your radio.\r\rYou made a backup, right?")
    ICOM.makebutt(
        'set_vfo_mem', b'\x09', 'Button', {}, 0,
        ICOM.do_not_poll_mask, 'Frequency', 9, 8, 1, 1, 'VFO>Mem', 0, 1, 10,
        "VFO to Mem:\r\rPuts the contents of your VFOs into memory. " \
        +"If you have split on, it will save both, with split setting. " \
        +"If no split, it will save top entry into both sides of the memory " \
        +"slot. Mode, filter, and tones are also saved. You can rename the memory " \
        +"with the Name Mem button.\r\rYou made a backup, right?")

    #ICOM.makebutt('set_mem_mode', b'\x08', 'Button', {}, 0,
    # ICOM.do_not_poll_mask, 'Frequency', 8, 7, 1, 1, 'MEM', 0, 1, 10)
    #ICOM.makebutt('set_mem_vfo', b'\x0A', 'Button', {}, 0,
    # ICOM.do_not_poll_mask, 'Frequency', 8, 8, 1, 1, 'M->V', 0, 1, 10)

    ICOM.makebutt(
        'set_vfo_mode', b'\x07', 'Button', {}, 0,
        ICOM.do_not_poll_mask, 'Frequency', 10, 6, 1, 1, 'VFO Mode', 0, 1, 10,
        "VFO Mode:\r\rSwitch from Memory to VFO, " \
        +"like the V/M button on the radio.")
    ICOM.makebutt(
        'set_vfo_equa', b'\x07\xA0', 'Button', {}, 0,
        ICOM.do_not_poll_mask, 'Frequency', 10, 7, 1, 1, 'A -> B', 0, 1, 10,
        "A -> B:\r\r Copy the top "
        +"VFO to the bottom (unselected) VFO. It actually doesn't care about A or B.")
    ICOM.makebutt(
        'set_vfo_swap', b'\x07\xB0', 'Button', {}, 0,
        ICOM.do_not_poll_mask, 'Frequency', 10, 8, 1, 1, 'A <> B', 0, 1, 10,
        "A <> B:\r\rSwap the selected and unselected "
        +"VFOs. This is the A/B button.")

    ICOM.makebutt(
        'split_on_off', b'\x0f', 'RadiobuttonTog', C_OFF_ON, 1,
        ICOM.poll_vfos_mask, 'Frequency', 11, 6, 1, 1, 'Split', 0, 1, 10,
        "Split Mode:\r\rTransmit on unselected VFO, Receive on selected VFO." \
        +"\r\rThis is the thing that stops people from shouting, \"Up! Up!\"")
    ICOM.makebutt(
        'rit_on_off', b'\x21\x01', 'RadiobuttonTog', C_OFF_ON, 1,
        ICOM.poll_controls_mask, 'Frequency', 11, 7, 1, 1, 'RIT', 0, 1, 10,
        "Receiver Incremental Tuning Mode:\r\rAllows tiny adjacent VFO to tune " \
        +"the receiver relative to selected VFO. The radio allows you to turn " \
        +"this and XIT on at the same time,  but you don't want to.")
    ICOM.makebutt(
        'rit_freq', b'\x21\x00', 'SmallVFO', C_RIT, 3,
        ICOM.poll_controls_mask, 'Frequency', 11, 8, 1, 1, 'RIT/XIT Offset', 0, 1, 6,
        "RIT Freq:\r\rScroll mouse wheel over digits to change." \
        +"\rFrom -9.999 to +9.9999.\r(-9.999k to +9.999k)")

    ICOM.makebutt(
        'dial_lock', b'\x16\x50', 'RadiobuttonTog', C_OFF_ON, 1,
        ICOM.poll_controls_mask, 'Frequency', 12, 6, 1, 1, 'Dial Lock', 0, 1, 10,
        "Dial Lock:\r\rKeeps you from fat-fingering the VFO knob" \
        +"\rand losing your frequency.")
    ICOM.makebutt(
        'xit_on_off', b'\x21\x02', 'RadiobuttonTog', C_OFF_ON, 1,
        ICOM.poll_controls_mask, 'Frequency', 12, 7, 1, 1, 'XIT', 0, 1, 10,
        "Transmitter Incremental Tuning:\r\rAllows tiny adjacent VFO to " \
        +"tune the transmitter relative to selected VFO.\rThe radio allows " \
        +"you to turn this and RIT on at the same time, \rbut you don't want to.")
    ICOM.makebutt(
        'rit_zero', 'xxxx', 'Button', {}, 1,
        ICOM.do_not_poll_mask, 'Frequency', 12, 8, 1, 1, 'Zero', 0, 1, 6,
        "Zero:\r\rZeroes RIT/XIT.")

    ############################ pwr frame
    ICOM.makebutt(
        'reconfig', b'reconfig', 'Button', {}, 0,
        ICOM.do_not_poll_mask, 'Power', 1, 1, 1, 1, 'Config', 0, 1, 7,
        "Reconfigure:\r\rThis removes the config file so you can start over.")
    ICOM.makebutt(
        'refresh', b'\x19\x00', 'Button', {}, 0,
        ICOM.do_not_poll_mask, 'Power', 1, 2, 1, 1, 'Refresh', 0, 1, 8,
        "Refresh:\r\rSends a polling command to the radio, \rmostly to refresh the " \
        +"program's copy of memory or keyer.")
    ICOM.makebutt(
        'set_power_on', b'\x18\x01', 'Button', {}, 0,
        ICOM.do_not_poll_mask, 'Power', 1, 3, 1, 1, 'Power On', 0, 1, 10,
        "Power On:\r\rSends power on command to the radio.")
    ICOM.makebutt(
        'set_power_off', b'\x18\x00', 'Button', {}, 0,
        ICOM.do_not_poll_mask, 'Power', 1, 4, 1, 1, 'Power Off', 0, 1, 10,
        "Power Off:\r\rSends power off command to the radio.")
    ICOM.makebutt(
        'timesync', b'\x19\x00', 'Button', {}, 0,
        ICOM.do_not_poll_mask, 'Power', 1, 5, 1, 1, 'Time Sync', 0, 1, 10,
        "Time Sync:\r\rShoves the computer clock value into the radio.")
    ICOM.makebutt(
        'quit', b'\x19\x00', 'Button', {}, 0,
        ICOM.do_not_poll_mask, 'Power', 1, 6, 1, 1, 'Quit', 0, 1, 6,
        "Quit:\r\rExits program without affecting radio.")
    ICOM.makebutt(
        'digi', b'digi', 'Button', {}, 0,
        ICOM.do_not_poll_mask, 'Power', 1, 7, 1, 1, 'Digi', 0, 1, 6,
        "Digi:\r\rSwitches radio to USB/DATA, no NR, no NB, no AGC, volume 0, and then starts JTDX or WSJTX.")
#    ICOM.makebutt(
#        'speed', b'', 'LabelCombobox', C_SPEED, 0,
#        ICOM.do_not_poll_mask, 'Power', 1, 7, 1, 1, 'Speed', 0, 1, 8,
#        "Speed:\r\rCPU Saver: After five seconds of no touching, sleeps longer " \
#        +"between poll cycles.\rModerate: After five seconds of no touch, sleeps " \
#        +"shorter between cycles.\rFast: CPU HOG and dang snappy.")
    ICOM.makebutt(
        'theme', b'theme', 'LabelCombobox', C_THEME, 0,
        ICOM.do_not_poll_mask, 'Power', 1, 10, 1, 1, 'Colors', 0, 1, 10,
        "Theme:\r\rChange the colors around just to be changing them.")
    ICOM.makebutt(
        'vscope', b'vscope', 'Button', C_OFF_ON, 1,
        ICOM.do_not_poll_mask, 'Power', 1, 9, 1, 1, 'Scope Window', 0, 1, 13,
        "Scope:\r\rThis is some experimental-ass bullshit here.")
    ICOM.makebutt(
        'band_plan', b'band_plan', 'RadiobuttonTog', C_OFF_ON, 1,
        ICOM.do_not_poll_mask, 'Power', 1, 8, 1, 1, 'Auto Mode', 0, 1, 13,
        "Auto Mode:\r\rChange modes according to band plan, CW, USB, LSB in ham bands, AM elsewhere, when changing frequency.")
    #ICOM.makebutt(
    #    'scopedata', b'\x27\x00', 'Software', {}, 500,
    #    ICOM.do_not_poll_mask, 'Power', 1, 9, 1, 1, 'Scope', 0, 1, 10,
    #    "Scope:\r\rThis is some experimental-ass bullshit here.")

    ############################ no physical control
    ICOM.makebutt(
        'radiodate', b'\x1a\x05\x00\x94', 'Software', C_FA_CODE, 4,
        ICOM.poll_vfos_mask, '', 0, 0, 0, 0, '', 0, 1, 0)
    ICOM.makebutt(
        'radiotz', b'\x1a\x05\x00\x96', 'Software', C_FA_CODE, 3,
        ICOM.poll_vfos_mask, '', 0, 0, 0, 0, '', 0, 1, 0)
    ICOM.makebutt(
        'radiotime', b'\x1a\x05\x00\x95', 'Software', C_FA_CODE, 2,
        ICOM.poll_vfos_mask, '', 0, 0, 0, 0, '', 0, 1, 0)
    ICOM.makebutt(
        'get_power_on', b'\x19\x00', 'Software', C_FA_CODE, 1,
        ICOM.do_not_poll_mask, '', 0, 0, 0, 0, '', 0, 1, 0)
    ICOM.makebutt(
        'FAILURE', b'\xfa', 'Software', C_FA_CODE, 1,
        ICOM.do_not_poll_mask, '', 0, 0, 0, 0, '', 0, 1, 0)
    ICOM.makebutt(
        'SUCCESS', b'\xfb', 'Software', C_FA_CODE, 1,
        ICOM.do_not_poll_mask, '', 0, 0, 0, 0, '', 0, 1, 0)
    ICOM.makebutt(
        'READ FREQ LOGGER', b'\x03', 'Software', C_FA_CODE, 5,
        ICOM.do_not_poll_mask, '', 0, 0, 0, 0, '', 0, 1, 0)
    ICOM.makebutt(
        'READ MODE LOGGER', b'\x04', 'Software', C_FA_CODE, 2,
        ICOM.do_not_poll_mask, '', 0, 0, 0, 0, '', 0, 1, 0)
    ICOM.makebutt(
        'SET FREQ LOGGER', b'\x05', 'Software', C_FA_CODE, 5,
        ICOM.do_not_poll_mask, '', 0, 0, 0, 0, '', 0, 1, 0)
    ICOM.makebutt(
        'SET MODE LOGGER', b'\x06', 'Software', C_FA_CODE, 2,
        ICOM.do_not_poll_mask, '', 0, 0, 0, 0, '', 0, 1, 0)
    ICOM.makebutt(
        'scope_fill_color', b'\x1a\x05\x01\x04', 'Software', C_FA_CODE, 6,
        ICOM.poll_keyer_mask, '', 0, 0, 0, 0, '', 0, 1, 0)
    ICOM.makebutt(
        'scope_line_color', b'\x1a\x05\x01\x05', 'Software', C_FA_CODE, 6,
        ICOM.poll_keyer_mask, '', 0, 0, 0, 0, '', 0, 1, 0)
    ICOM.makebutt(
        'scope_peak_color', b'\x1a\x05\x01\x06', 'Software', C_FA_CODE, 6,
        ICOM.poll_keyer_mask, '', 0, 0, 0, 0, '', 0, 1, 0)
    ICOM.makebutt(
        'my_call', b'\x1a\x05\x00\x91', 'Software', C_FA_CODE, 10,
        ICOM.poll_keyer_mask, '', 0, 0, 0, 0, '', 0, 1, 0)
    ICOM.makebutt(
        'mem_ch', b'\x1a\x00', 'Software', C_FA_CODE, 41,
        ICOM.poll_mem_mask, '', 0, 0, 0, 0, '', 0, 1, 0)
    ICOM.makebutt(
        'ovf', b'\x15\x07', 'Software', C_FA_CODE, 1,
        ICOM.poll_meters_mask, '', 0, 0, 0, 0, '', 0, 1, 0)

    img=images()
    swr_meter_face=tkinter.PhotoImage(data=img.swr_base64)
    pwr_meter_face=tkinter.PhotoImage(data=img.pwr_base64)
    alc_meter_face=tkinter.PhotoImage(data=img.alc_base64)
    s_meter_face=tkinter.PhotoImage(data=img.s_base64)

    ICOM.widget_object['swr_meter_scale'] = \
        tkinter.Label(ICOM.widget_object['Meters'],image=swr_meter_face,padx=0,pady=0,borderwidth=0)\
        .grid(row=2,rowspan=3,column=1,columnspan=10,padx=0,pady=(0,0),ipadx=0,ipady=0)

    ICOM.widget_object['pwr_meter_scale'] = \
        tkinter.Label(ICOM.widget_object['Meters'],image=pwr_meter_face,padx=0,pady=0,borderwidth=0)\
        .grid(row=6,rowspan=3,column=1,columnspan=10,padx=0,pady=(0,0),ipadx=0,ipady=0)

    ICOM.widget_object['alc_meter_scale'] = \
        tkinter.Label(ICOM.widget_object['Meters'],image=alc_meter_face,padx=0,pady=0,borderwidth=0)\
        .grid(row=1,rowspan=3,column=11,columnspan=10,padx=0,pady=(0,0),ipadx=0,ipady=0)

    ICOM.widget_object['s_meter_scale'] = \
        tkinter.Label(ICOM.widget_object['Meters'],image=  s_meter_face,padx=0,pady=0,borderwidth=0)\
        .grid(row=5,rowspan=3,column=11,columnspan=10,padx=0,pady=(0,0),ipadx=0,ipady=0)

    if config.config_value['baud'] == '115200':
        ICOM.build_scope()

    temp_list = dict()
    ICOM.poll_list[ICOM.poll_mem_mask] = Node(None)
    ICOM.poll_list[ICOM.poll_keyer_mask] = Node(None)
    ICOM.poll_list[ICOM.poll_vfos_mask] = Node(None)
    ICOM.poll_list[ICOM.poll_scope_mask] = Node(None)
    ICOM.poll_list[ICOM.poll_controls_mask] = Node(None)
    ICOM.poll_list[ICOM.poll_meters_mask] = Node(None)

    # save these temporarily
    temp_list[ICOM.poll_mem_mask] = ICOM.poll_list[ICOM.poll_mem_mask]
    temp_list[ICOM.poll_keyer_mask] = ICOM.poll_list[ICOM.poll_keyer_mask]
    temp_list[ICOM.poll_vfos_mask] = ICOM.poll_list[ICOM.poll_vfos_mask]
    temp_list[ICOM.poll_scope_mask] = ICOM.poll_list[ICOM.poll_scope_mask]
    temp_list[ICOM.poll_controls_mask] = ICOM.poll_list[ICOM.poll_controls_mask]
    temp_list[ICOM.poll_meters_mask] = ICOM.poll_list[ICOM.poll_meters_mask]


    for comand in ICOM.poll_type:
        num = ICOM.poll_type[comand]
        ICOM.poll_list[num].next = Node(comand)
        ICOM.poll_list[num] = ICOM.poll_list[num].next

    # The first item in each list is a junker on purpose, so point to the temp link's 'next' one.
    for num in (ICOM.poll_mem_mask,
                ICOM.poll_keyer_mask,
                ICOM.poll_vfos_mask,
                ICOM.poll_scope_mask,
                ICOM.poll_controls_mask,
                ICOM.poll_meters_mask):
        ICOM.poll_list[num].next = temp_list[num].next
        ICOM.poll_list[num] = temp_list[num].next
        ICOM.poll_first[num] = temp_list[num].next


#    if config.config_value['cpu_mode'] == 'Fast':
#        ICOM.widget_object['speed'].current(2)
#    elif config.config_value['cpu_mode'] == 'Moderate':
#        ICOM.widget_object['speed'].current(1)
#    elif config.config_value['cpu_mode'] == 'CPU Saver':
#        ICOM.widget_object['speed'].current(0)
#    else:
#        ICOM.widget_object['speed'].current(0)

    ICOM.widget_object['theme'].set(config.config_value['theme'])

    root.IN_ENTRY = False
    #root.bind("<Escape>", handle_escape_key)
    root.bind("<Control-w>", quit_prog)

    root.protocol("WM_DELETE_WINDOW", quit_prog)
    root.title("PyC-7300")

    if config.config_value['geom'] != '':
        root.geometry(config.config_value['geom'])
    if 'scopegeom' in config.config_value.keys():
        if config.config_value['scopegeom'] != '':
            if config.config_value['baud'] == '115200':
                ICOM.scopewin.geometry(config.config_value['scopegeom'])

    if config.config_value['theme'] != '':
        pal = ICOM.gui_theme[config.config_value['theme']]
        root.tk_setPalette(**pal)
        #tkinter.ttk.Style().configure("TProgressbar", **pal)
        tkinter.ttk.Style().configure("TProgressbar",background='#ff0000',troughcolor='#182c40',thickness=3,troughrelief=tkinter.FLAT)
        tkinter.ttk.Style().configure("TCombobox", **pal)

    stuff_startup_cmds()

    # set gui_touched to now to make it fast for the initial load even if the user set it slowly
    pollsplash()
    while True and CO.quitq.empty():
        receivecycle()
