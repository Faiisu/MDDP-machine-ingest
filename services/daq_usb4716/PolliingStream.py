#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
/*******************************************************************************
Copyright (c) 1983-2024 Advantech Co., Ltd.
********************************************************************************
Permission is hereby granted, free of charge, to any person obtaining a copy of 
this software and associated documentation files (the "Software"), to deal in  
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
of the Software, and to permit persons to whom the Software is furnished to do
so,  subject to the following conditions: 
 
The above copyright notice and this permission notice shall be included in all  
copies or substantial portions of the Software. 
 
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A  PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE. 

================================================================================
REVISION HISTORY
--------------------------------------------------------------------------------
$Log:  $
--------------------------------------------------------------------------------
$NoKeywords:  $
*/
/******************************************************************************
*
* Windows Example:
*    PollingStramingAI.py
*
* Example Category:
*    AI
*
* Description:
*    This example demonstrates how to use Polling Streaming AI function.
*
* Instructions for Running:
*    1. Login the edge by hostName. If you'd like to handle a local device 
*       (i.e. USB or PCI/PCIe interfaced device in your PC), please bypass this
*       step.
*    2. Set the 'deviceDescription' which can get from system device manager for
*       opening the device.
*    3. Set the 'profilePath' to save the profile path of being initialized
*       device.
*    4. Set the 'startChannel' as the first channel for scan analog samples
*    5. Set the 'channelCount' to decide how many sequential channels to scan
*       analog samples.
*    6. Set the 'sectionLength' as the length of data section for Buffered AI.
*    7. Set the 'sectionCount' as the count of data section for Buffered AI.
*
* I/O Connections Overview:
*    Please refer to your hardware reference manual.
*
******************************************************************************/
"""
import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__),
                                             os.path.pardir)))
from CommonUtils import kbhit

from Automation.BDaq import *
from Automation.BDaq.WaveformAiCtrl import WaveformAiCtrl
from Automation.BDaq.BDaqApi import AdxEnumToString, BioFailed

# Configure the following parameters before running the demo
deviceDescription = "iDAQ-801,BID#0"
profilePath = u"../../profile/DemoDevice.xml"

startChannel = 0
channelCount = 4

sectionLength = 1024
sectionCount = 0

userParam = DaqEventParam()

@DaqEventCallback(None, c_void_p, POINTER(BfdAiEventArgs), c_void_p)
def OnBurnoutEvent(sender, args, userParam):
    status  = cast(args, POINTER(BfdAiEventArgs))[0]
    channel = status.Offset
    print("AI Channel%d is burntout!" % (channel))

# user buffer size should be equal or greater than raw data buffer length,
# because data ready count is equal or more than smallest section of raw data
# buffer and up to raw data buffer length. users can set 'USER_BUFFER_SIZE'
# according to demand.
USER_BUFFER_SIZE = channelCount * sectionLength

def AdvPollingStreamingAI():
    ret = ErrorCode.Success

    # Step 1: Create a 'WaveformAiCtrl' for Buffered AI function
    # Login an Edge Server by hostname for remote control
    # Select a device by device number or device description and specify the
    # access mode.
    # In this example we use ModeWrite mode so that we can use fully control
    # the device,
    # including configuring, sampling, etc
    wfAiCtrl = WaveformAiCtrl(deviceDescription)
    wfAiCtrl.addBurnOutHandler(OnBurnoutEvent, userParam)

    for _ in range(1):
        # Loads a profile to initialize the device
        wfAiCtrl.loadProfile = profilePath
        
        # Step 2: Set necessary parameters for Streaming AI operation
        # get the Conversion instance and set the start channel and scan channel
        # number
        wfAiCtrl.conversion.channelStart = startChannel
        wfAiCtrl.conversion.channelCount = channelCount
        wfAiCtrl.conversion.clockRate    = 1000

        # get the record instance and set record count and section length
        # The 0 means setting 'streaming' mode
        wfAiCtrl.record.sectionCount = sectionCount  
        wfAiCtrl.record.sectionLength = sectionLength

        for i in range(channelCount):
            wfAiCtrl.channels[startChannel + i].signalType      = AiSignalType.PseudoDifferential
            wfAiCtrl.channels[startChannel + i].valueRange      = ValueRange.V_Neg12To12
            wfAiCtrl.channels[startChannel + i].couplingType    = CouplingType.ACCoupling
            wfAiCtrl.channels[startChannel + i].iepeType        = IepeType.IEPE2mA
            wfAiCtrl.channels[startChannel + i].burnoutRetType  = BurnoutRetType.ParticularValue
            wfAiCtrl.channels[startChannel + i].burnoutRetValue = 11

        # Step 3: The operation has been started
        ret = wfAiCtrl.prepare()
        if BioFailed(ret):
            break

        ret = wfAiCtrl.start()
        if BioFailed(ret):
            break

        # Step 4: The device is acquisition data with Polling Style
        print("Polling infinite acquisition is in progress, any key to quit!")
        while not kbhit():
            result = wfAiCtrl.getData(USER_BUFFER_SIZE, -1)
            ret, returnedCount, data, = result[0], result[1], result[2]
            if BioFailed(ret):
                break

            print("Polling Stream AI get data count is %d" % returnedCount)

            print("the first sample for each channel are:")
            for i in range(channelCount):
                print("channel %d: %10.6f" % (i + startChannel, data[i]))

        # Step 6: Stop the operation if it is running
        ret = wfAiCtrl.stop()

        # Step 7: Release any allocated resource
        wfAiCtrl.release()

    # Step 8: Logout from server.
    #wfAiCtrl.logout()
    
    # Step 9: Close device, release any allocated resource
    wfAiCtrl.dispose()

    # If something wrong in this execution, print the error code on screen for
    # tracking
    if BioFailed(ret):
        enumStr = AdxEnumToString("ErrorCode", ret.value, 256)
        print("Some error occurred. And the last error code is %#x. [%s]" %
              (ret.value, enumStr))
    return 0


if __name__ == '__main__':
    AdvPollingStreamingAI()
