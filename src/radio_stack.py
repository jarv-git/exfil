# This is code for a configurable radio stack; it can be used for
# either the host or the xfil unit

import sys
import time
sys.path.append('../src')
import zmq_utils as zmu
import rf_mgt as rfm
import tx_top
import rx_top
import signal

class RadioStack():
    def __init__(self,
                 rx_rf_params,
                 rx_bb_params,
                 tx_rf_params,
                 tx_bb_params,
                 tcp_params,
                 sdr_sel = rfm.HW_TEST):

        # local variable copies
        self.rx_rf_params = rx_rf_params
        self.rx_bb_params = rx_bb_params
        self.tx_rf_params = tx_rf_params
        self.tx_bb_params = tx_bb_params
        self.tcp = tcp_params
        self.verbose = False

        # the sdr selection needs to stay the same
        self.sdr_sel = sdr_sel

        # create the zmq variables, assign as needed
        self.tx_zmq = None
        self.rx_zmq = None
        # open zmq socket for payload xfr to tx flowgraph
        #self.tx_zmq = zmu.ZmqPushMsgSocket(self.tcp.tx)

        # open zmq socket for payload xfr from rx flowgraph
        #self.rx_zmq = zmu.ZmqPullMsgSocket(self.tcp.rx)


    # switch to receive mode, stopping tx flowgraph and starting
    # an rx flowgraph
    def switch_to_rx(self):
        # shutdown any existing flowgraphs
        self.shutdown()

        # instance an rx flowgraph with current settings
        self.fg_rx = rx_top.RxTop(rf_params=self.rx_rf_params,
                                  bb_params=self.rx_bb_params,
                                  tcp_addr=self.tcp.rx,
                                  tcp_test=self.tcp.test_rx,
                                  sdr_sel=self.sdr_sel)

        # open zmq socket for payload xfr from rx flowgraph
        self.rx_zmq = zmu.ZmqPullMsgSocket(self.tcp.rx)

        self.fg_rx.start()

    # switch to transmit mode, stopping rx flowgraph and starting
    # a tx flowgraph
    def switch_to_tx(self):
        # shutdown receive flowgraph
        self.shutdown()

        # instance a tx flowgraph with current uplink settings
        self.fg_tx = tx_top.TxTop(rf_params=self.tx_rf_params,
                                  bb_params=self.tx_bb_params,
                                  tcp_addr=self.tcp.tx,
                                  tcp_test=self.tcp.test_tx,
                                  sdr_sel=self.sdr_sel)

        # open zmq socket for payload xfr to tx flowgraph
        self.tx_zmq = zmu.ZmqPushMsgSocket(self.tcp.tx)

        self.fg_tx.start()

    # update configuration for receive connection
    def set_rx_config(self, rf_params, bb_params):
        self.rx_rf_params = rf_params
        self.rx_bb_params = bb_params

    # set or update configuration for transmit connection
    def set_tx_config(self, rf_params, bb_params):
        self.tx_rf_params = rf_params
        self.tx_bb_params = bb_params

    # send the current uplink parameters in byte form
    # this tells the downstream radio how to configure its transmitter
    # so that it can communicate with this radio's current rx settings
    def send_uplink_config(self):
        if self.verbose:
            print self.rx_rf_params.params_to_bytes()
            print self.rx_bb_params.params_to_bytes()
        cmd_bytes = self.rx_rf_params.params_to_bytes()
        cmd_bytes += self.rx_bb_params.params_to_bytes()
        self.send_bytes(tx_bytes=cmd_bytes)

    # uses zmq interface to send byte data to tx fg, which transmits
    def send_bytes(self, tx_bytes):
        # add checksum to commands
        combo_bytes = tx_bytes[:]
        combo_bytes.append(rfm.acs(tx_bytes))
        self.tx_zmq.send_framed_bytes(
            preamble=self.tx_bb_params.preamble_bytes,
            byte_list=combo_bytes,
            verbose=self.verbose)

    # uses zmq interface to send string data to tx fg
    def send_str(self, tx_str):
        byte_list = bytearray(tx_str)
        self.send_bytes(byte_list)

    # receives raw bytes from rx flowgraph via zmq; it then checks
    # the last byte, assuming that it contains an arithmetic checksum
    def recv_bytes(self, verbose=False):
        # wait for valid transmission
        raw_data = self.rx_zmq.poll_bytes(self.verbose)

        # checksum
        cs_computed = rfm.acs(raw_data[:-1])
        if verbose:
            print "Raw data bytes:",
            print raw_data
            print "Checksum: {}".format(cs_computed)

        # if we have a valid payload, else return empty list
        if cs_computed == raw_data[-1]:
            #if the payload is the dummy payload, ignore it
            if raw_data[:-1] != rfm.DUMMY_PAYLOAD:
                return raw_data[:-1]
            else:
                return []
        else:
            return []

    # converts received bytes to string
    def recv_str(self, verbose=False):
        raw_bytes = bytearray(self.recv_bytes(verbose=verbose))
        try:
            ret_str = raw_bytes.decode()
        except:
            ret_str = ""
        return ret_str

    # timeout handler function
    def handler(self, signum, frame):
        raise Exception("Receiver timeout...")

    # the host may attempt to request data from the xfil box but may
    # not receive it; to keep it from hanging, it should use this
    # function which adds a timeout capability; the xfil box should use
    # the recv_bytes above, without timeout
    # Note: default is 10 seconds
    def recv_bytes_timeout(self, timeout=10, verbose=False):
        # define a signal that implements the timeout alarm
        signal.signal(signal.SIGALRM, self.handler)
        signal.alarm(10)
        try:
            return_val = self.recv_bytes()
        except Exception, exc:
            return_val = []
        signal.alarm(0)
        return return_val

    # same as above but with strings
    def recv_str_timeout(self, timeout=2, verbose=False):
        # define a signal that implements the timeout alarm
        signal.signal(signal.SIGALRM, self.handler)
        signal.alarm(timeout)
        try:
            return_val = self.recv_str(verbose=verbose)
        except Exception, exc:
            return_val = []
        signal.alarm(0)
        return return_val

    # to keep from operating tx and rx simultaneously
    def rx_shutdown(self):
        if 'fg_rx' in vars(self):
            self.fg_rx.stop()
            time.sleep(1) # doesn't work without this
            del self.fg_rx

    def tx_shutdown(self):
        if 'fg_tx' in vars(self):
            self.fg_tx.stop()
            time.sleep(1) # doesn't work without this
            del self.fg_tx

    # shut down both
    def shutdown(self):
        self.rx_shutdown()
        self.tx_shutdown()
        # close sockets and destroy context
        if self.tx_zmq is not None:
            self.tx_zmq.close()
        if self.rx_zmq is not None:
            self.rx_zmq.close()
