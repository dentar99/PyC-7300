![PyC-7300](https://user-images.githubusercontent.com/76819904/107884009-6f005100-6ec0-11eb-9d48-b85d24d501ea.png)

        ******* USE AT YOUR OWN RISK *******

        ******* BACK UP YOUR IC-7300 *******

        *******  NO SUPPORT OFFERED  *******


PyC-7300 was written solely as an educational venture during the COVID-19
pandemic of 2020.  I learned quite a bit about CI-V from this, and got
pretty good control of the IC-7300 from the computer.

This program works with the firmware version 1.3.  It might work with 
the older one, but not tested.

This program is optimized to use Python v3.  It will likely not run at all
under version 2 of Python.  Any version 3.5.6 or better should work.

To use the scope, you need 115,200 baud and unlink from remote on your
rig.  If you don't know what that means, go to Icom's web site and 
download the user manual for your version of the radio and find out
how to do this.

These are the three stupidest shortcomings in CI-V for this radio as well:

	1: You cannot edit the name for a voice keyer entry with CI-V,
           but you can send a voice keyer entry with it.
	2: You can edit a CW keyer entry with CI-V, but you can't 
           transmit one.  This program fakes it by sending raw 
           ASCII versions of what's already in your keyer.
     	3: If you turn off AGC with noise reduction turned on, the radio
           can start to oscillate.  The cure for this is to power the 
           radio off and on again and then either turn AGC on or NR off.

This program does not pipe audio in either direction, just does the 
CI-V back and forth from the radio.

This program does work on the Raspberry Pi 3 and 4.  You probably want the 4.

This program also works in "regular" Linux.

The code is sloppy and experimental, and is not a "professional" product.

Before running this program, be sure the below statements work with
your Python > 3.5.6 interpreter on your system:

import sys
import math
import textwrap
import collections
import time
import multiprocessing
import tkinter
import tkinter.ttk
import tkinter.messagebox
import tkinter.simpledialog
import os
import shutil
import serial.tools.list_ports
import termios
import fcntl
import struct
import socket
import select

After you verify that, the USB port on Linux (to which your radio is hooked) 
may be something like /dev/ttyUSB0.


