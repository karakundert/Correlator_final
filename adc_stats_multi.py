#	Eddie Toral
#	CAMPARE Summer 2016 Research Undergrad
#	August 16th, 2016
#	
#	Simple model used to obtain data to determine analog input level to digital output level relationship.
#	75.0 MHz single tone from input levels +12dBm to -36.0 dBm.
#	Direct connection to input of SNAP Board, no attenuators or filters used during testing.
#	Only 1 antenna at a time, selectable by [option] -a to be selected when running script
#	adc_stats_2016-8-16_1606.bof

#from argparse import ArgumentParser
#p = ArgumentParser(description = 'python adc_stats.py [options] ')
#p.add_argument('host', type = str, default = '10.0.1.217', help = 'Specify the host name')
#p.add_argument('-a', '--antenna', dest = 'antenna', type = int, default = 0, help = 'antenna selection')

#args = p.parse_args()
#host = args.host
#antenna = args.antenna

host = 'rpi2-3'
antenna = 11
scale = 1024
#scale = 362

import corr, struct, numpy as np, matplotlib.pyplot as plt, time
s = corr.katcp_wrapper.FpgaClient(host,7147,timeout = 10)
time.sleep(1)
s.write_int('antenna', antenna)
scale_ant = 'scale{x}'.format(x=antenna)
s.write_int(scale_ant, scale)
s.write_int('prequant_select', antenna)
s.write_int('postquant_select', antenna)
s.write_int('prequant_ctrl', 1)
s.write_int('postquant_ctrl', 1)
s.write_int('prequant_ctrl', 0)
s.write_int('postquant_ctrl', 0)
s.write_int('adc_stats_ctrl', 1)
s.write_int('adc_stats_ctrl', 0)

adc_stats = s.snapshot_get('adc_stats',man_trig=True,man_valid=True)
stats = struct.unpack('>256b',adc_stats['data'])
stats = np.asarray(stats)
prequant_data = s.snapshot_get('prequant',man_trig=True,man_valid=True)
preq = struct.unpack('>256q',prequant_data['data'])
npreq = []
for each in preq:
    if each > 2**35-1:
        each = -(2**36-each)
    npreq.append(each)
    print "%o" % each, type(each)
preq = npreq
preq = np.asarray(preq)
preq_top = preq >> 18 
preq_bottom = 0x3FFFF & preq
postquant_data = s.snapshot_get('postquant',man_trig=True,man_valid=True)
postq = struct.unpack('>256b',postquant_data['data'])
tpostq = []
bpostq = []
postq_rms = 0
for each in postq:
    top = (each >> 4) & 0x0F
    if top > 2**3-1:
        top = -(2**4-top)
    tpostq.append(top)
    bot = each & 0x0F
    if bot > 2**3-1:
        bot = -(2**4-bot)
    bpostq.append(bot)
    postq_rms += top**2 + bot**2
real = np.asarray(tpostq)
imag = np.asarray(bpostq)

rms = np.sqrt(np.mean(np.square(stats)))
print "Hey this one is the ADC rms"
print rms

preq_rms = np.sqrt(np.mean(np.square(preq)))
print "Hey this one is the prequantization rms"
print preq_rms

postq_rms = np.sqrt(1.0*postq_rms/len(real))
print "Hey this one is the postquantization rms"
print postq_rms

plt.figure(1)
title = 'ADC Data: Antenna {i}'.format(i=antenna)
plt.title(title)
plt.plot(stats,'k')
plt.axis([0,256,-136,135])
plt.grid(True)

plt.figure(2)
plt.hist(stats, bins=256) 
plt.title("Histogram with 256 bins")

plt.figure(3)
title = 'Pre-Quantization Data: Antenna {i}'.format(i=antenna)
plt.title(title)
plt.plot(preq,'k')
#plt.axis([0,256,-68719476736,68719476735])
plt.grid(True)

plt.figure(4)
plt.hist(preq, bins=256) 
plt.title("Histogram with 256 bins")

plt.figure(5)
title = 'Post-Quantization Data: Antenna {i}'.format(i=antenna)
plt.title(title)
plt.plot(real,'r', label='real')
plt.plot(imag,'b', label='imag')
plt.legend()
#plt.axis([0,256,-136,135])
plt.grid(True)

plt.figure(6)
plt.hist(postq, bins=256) 
plt.title("Histogram with 256 bins")
plt.show()
