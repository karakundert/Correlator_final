import time
import struct
#import corr
import casperfpga
import argparse
import sys
import numpy as np
import cPickle as pickle
import subprocess

NCHANS = 512
ADC_CLK = 250e6

def get_data(r, ant_list):
    """
    Return a dictionary of numpy data arrays, which may or may not be complex
    """
    rv = {}
    for x in np.arange(len(ant_list)):
        i = ant_list[x]
        auto = '{i}_auto'.format(i=i)
        rv[auto] = get_auto_corr(r, i)
        for y in np.arange(len(ant_list)):
            j = ant_list[y]
            if i < j:
                cross = '{i}_{j}_cross'.format(i=i,j=j)
                rv[cross] = get_cross_corr(r, i, j)
    return rv

def get_auto_corr(r, i):
    """
    Return the real auto-correlation data array.
    """
    auto_reg = 'ac_a{i}_real'.format(i=i)
    return np.fromstring(r.read(auto_reg, 4*NCHANS), dtype='>i4')

def get_cross_corr(r, i, j):
    """
    Return the complex cross-correlation data array.
    """
    real_reg = 'cc_a{i}_a{j}_real'.format(i=i,j=j)
    imag_reg = 'cc_a{i}_a{j}_imag'.format(i=i,j=j)
    return (
            np.fromstring(r.read(real_reg, 4*NCHANS), dtype='>i4') 
            + 1j*np.fromstring(r.read(imag_reg, 4*NCHANS), dtype='>i4')
    )

def write_file(d, times, freqs, inttime, prefix='dat_poco_snap_multi'):
    fname = prefix + '-%s.npz' % time.time()
    print 'Writing %s' % fname,
    t0 = time.time()
    np.savez(fname, times=times, freqs=freqs, inttime=inttime, **d)
    t1 = time.time()
    print 'Done in %.2f seconds' % (t1-t0)
        

def get_pi_temp():
    # read temp off RPI
    pi_temp = subprocess.check_output('cat /sys/class/thermal/thermal_zone0/temp',shell=True)
    # convert to 32bit integer
    return np.int32(pi_temp)

def get_fpga_temp(fpga):
    # returns SNAP FPGA core temperature
    TEMP_OFFSET = 0x0
    reg = 'xadc'
    x = fpga.read_int(reg, TEMP_OFFSET)
    return (x >> 4) * 503.975 / 4096. - 273.15

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--prog', action='store_true', default=False,
                        help='Use this flag to program the FPGA (THIS SCRIPT DOES NOT DO ADC CALIBRATION)')
    parser.add_argument('-b', '--boffile', default='quantized.bof',
                        help='Which boffile to program')
    parser.add_argument('-f', '--fftshift', type=int, default=0xffff,
                        help='FFT shift schedule as an integer. Default: 0xffff')
    parser.add_argument('-a', '--acc_len', type=int, default=2**20,
                        help='Number of spectra to accumulate. Default: 2^20')
    parser.add_argument('-t', '--filetime', type=int, default=600,
                        help='Time in seconds of each data file. Default: 600')
    parser.add_argument('-s', '--snap', default='10.10.10.101',
                        help='SNAP hostname of IP. Default: 10.10.10.101')
    parser.add_argument('-c', '--scale', type=int, default=1024,
                        help='Scale coefficient')
    parser.add_argument('-A', '--antennas', type=int, nargs='+',
                        default=[3,4,7,8],
                        help='List of antennas to correlate, based on SNAP input number')

    opts = parser.parse_args()
    ants = opts.antennas
    print ants
    scale = opts.scale

    #if len(args) == 0:
    #    print 'No SNAP hostname given. Usage: poco_snap_simple.py [options] <katcp_host>'

    print 'Connecting to %s' % opts.snap
    #r = corr.katcp_wrapper.FpgaClient(opts.snap)
    r = casperfpga.CasperFpga(opts.snap)
    time.sleep(0.05)

    if r.is_connected():
        print 'Connected!'
    else:
        print 'Failed to Connect!'
        exit()

    if opts.prog:
        print 'Trying to program with boffile %s' % opts.boffile
        print '(You probably don\'t want to do this -- this script won\'t configure the ADCs)'
        if opts.boffile in r.listbof():
            #r.progdev(opts.boffile)
            r.upload_to_ram_and_program(opts.boffile)
            print 'done'
        else:
            print 'boffile %s does not exist on server!' % opts.boffile
            exit()

    #print 'FPGA board clock is', r.est_brd_clk()
    print 'FPGA board clock is', r.estimate_board_clock()

    # Configure registers
    print 'Setting FFT shift to %x' % opts.fftshift
    r.write_int('shift', opts.fftshift & 0xffff)
    print 'Checking for FFT overflows...'
    oflow = False
    for i in range(5):
        oflow = oflow or bool(r.read_int('overflow'))
        time.sleep(1)
    if oflow:
        print 'Overflows detected -- consider increasing FFT shift'
    else:
        print 'No overflows detected'

    print 'Setting accumulation length to %d spectra' % opts.acc_len,
    print '(%.2f seconds)' % (opts.acc_len * 2 * NCHANS / ADC_CLK)
    r.write_int('acc_len', 1024*opts.acc_len-1) #converting from accumulation number to clock cycles (zero indexed)
    inttime = 1024*opts.acc_len / ADC_CLK # seconds
    print 'Integration time: %f seconds' % inttime
    for i in xrange(len(ants)):
        scale_i = 'scale{x}'.format(x=ants[i])
        r.write_int(scale_i, scale)

    print 'Triggering sync'
    r.write_int('trig', 0)
    r.write_int('trig', 1)
    trig_time = time.time()
    r.write_int('trig', 0)

    this_acc = 0
    this_acc_time = trig_time
    file_start_time = time.time()
    data  = {}
    times = []
    freqs = np.arange(0, ADC_CLK/2, ADC_CLK/2/NCHANS)
    while(True):
        try:
            print get_pi_temp()
            print get_fpga_temp(r)
            latest_acc = r.read_uint('acc_num')
            latest_acc_time = time.time()
            if latest_acc == this_acc:
                time.sleep(0.05)
            elif latest_acc == this_acc + 1:
                print 'Got %d accumulation after %.2f seconds' % (latest_acc, (latest_acc_time - this_acc_time))
                new_data = get_data(r, ant_list=ants)
                for key in new_data:
                    data[key] = data.get(key,[]) + [new_data[key]]
                times += [latest_acc_time]
                this_acc = latest_acc
                this_acc_time = latest_acc_time
                if time.time() > (file_start_time + opts.filetime):
                    write_file(data, times, freqs, inttime)
                    file_start_time = time.time()
                    data  = {}
                    times = []
            else:
                print 'Last accumulation was number %d' % this_acc,
                print 'Next accumulation is number %d' % latest_acc,
                print 'Bad!'
                this_acc = latest_acc
                this_acc_time = latest_acc_time
        except KeyboardInterrupt:
            'Exiting'
            write_file(data, times, freqs, inttime)
            exit()
