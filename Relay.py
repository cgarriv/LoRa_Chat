import time
import random
import threading


class RelayManager:
    def __init__(self, messenger):
        self.messenger = messenger
        self.seen_messages = set()
        self.lock = threading.Lock()
        self.cts_ack_received = False
        self.responding_node = None
        self.awaited_cts_seq = None

    def has_seen(self, from_addr, seq_num):
        return (from_addr, seq_num) in self.seen_messages

    def mark_seen(self, from_addr, seq_num):
        with self.lock:
            self.seen_messages.add((from_addr, seq_num))

    def build_message(self, from_addr, to_addr, seq_num, flags, hops, msg):
        return f"FROM:{from_addr}|TO:{to_addr}|SEQ:{seq_num}|FLAGS:{flags:08b}|HOPS:{','.join(hops)}|MSG:{msg}"

    def parse_message(self, raw):
        parts = dict(part.split(":", 1) for part in raw.split("|") if ':' in part)
        parts['SEQ'] = int(parts['SEQ'])
        parts['FLAGS'] = int(parts['FLAGS'], 2)
        parts['HOPS'] = parts['HOPS'].split(',') if 'HOPS' in parts else []
        return parts

    def handle_incoming(self, raw, from_addr):
        msg = self.parse_message(raw)
        seq_key = (msg['FROM'], msg['SEQ'])

        if self.has_seen(*seq_key):
            return
        self.mark_seen(*seq_key)

        if msg['TO'] == self.messenger.myAddress:
            print(f"[DIRECT MESSAGE] From {msg['FROM']}: {msg['MSG']}")
            # Send ACK
            if msg['FLAGS'] & 0b00000001:
                ack_msg = self.build_message(
                    from_addr=self.messenger.myAddress,
                    to_addr=msg['FROM'],
                    seq_num=int(time.time()),
                    flags=0b00000001,
                    hops=[str(self.messenger.myAddress)],
                    msg=f"ACK for SEQ {msg['SEQ']}"
                )
                self.messenger.send(ack_msg, msg['FROM'])
            return

        # Check if we are waiting on a CTS ACK
        if (msg['FLAGS'] & 0b00100001) == 0b00100001 and msg['SEQ'] == self.awaited_cts_seq:
            self.cts_ack_received = True
            self.responding_node = msg['FROM']

        # Relay logic
        msg['HOPS'].append(str(self.messenger.myAddress))
        new_msg = self.build_message(msg['FROM'], msg['TO'], msg['SEQ'], msg['FLAGS'], msg['HOPS'], msg['MSG'])

        for neighbor in self.messenger.tr.pageTable:  # TODO: Replace with actual page table from training
            if neighbor != from_addr:
                self.messenger.send(new_msg, neighbor)
                print(f"[RELAY] Forwarded to {neighbor} for destination {msg['TO']}")

    def broadcast_cts(self, target, timeout=30):
        seq = int(time.time())
        self.awaited_cts_seq = seq
        self.cts_ack_received = False
        self.responding_node = None

        flags = 0b00001000  # CTS (bit 3)
        msg = self.build_message(self.messenger.myAddress, target, seq, flags, [str(self.messenger.myAddress)], "CTS")
        self.messenger.send(msg, 0)  # Broadcast
        print(f"[CTS] Sent CTS for {target}, waiting {timeout}s for replies")

        threading.Thread(target=self.await_cts_response, args=(seq,)).start()

    def await_cts_response(self, seq):
        for _ in range(30):  # Wait up to 30 seconds
            if self.cts_ack_received:
                print(f"[CTS] Got ACK from {self.responding_node} for SEQ {seq}")
                # TODO: Send actual message relaying here
                return
            time.sleep(1)

        print(f"[CTS] Timeout: No ACK for SEQ {seq}")