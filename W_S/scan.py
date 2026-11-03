import socket
import ipaddress
import struct
import time
from threading import Thread, Lock
from utile.display import console

class NetworkScanner:
    def __init__(self, target_input):
        self.target_input = target_input
        self.open_ports = []
        self.lock = Lock()

    def get_targets(self):
        """Transforme l'entrée utilisateur en une liste d'IP valides"""
        targets = []
        try:
            if '-' in self.target_input:
                start_ip, end_val = self.target_input.split('-')
                start_ip = start_ip.strip()
                end_val = end_val.strip()

                if '.' in end_val:
                    start = int(ipaddress.IPv4Address(start_ip))
                    end = int(ipaddress.IPv4Address(end_val))
                else:
                    prefix = start_ip.rsplit('.', 1)[0]
                    start = int(ipaddress.IPv4Address(start_ip))
                    end = int(ipaddress.IPv4Address(f"{prefix}.{end_val}"))
                
                for ip_int in range(start, end + 1):
                    targets.append(str(ipaddress.IPv4Address(ip_int)))
            
            elif '/' in self.target_input:
                network = ipaddress.ip_network(self.target_input, strict=False)
                for ip in network.hosts():
                    targets.append(str(ip))
            
            else:
                targets.append(self.target_input)
                
        except Exception as e:
            console.print(f"[error][!] Format d'IP invalide : {e}[/error]")
        return targets

    def check_port(self, ip, port):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.4)
            result = s.connect_ex((ip, port))
            if result == 0:
                with self.lock:
                    self.open_ports.append((ip, port))
                    console.print(f"[success][+] {ip}:{port} ouvert ![/success]")
            s.close()
        except: pass

    def run_scan(self):
        targets = self.get_targets()
        if not targets: return

        common_ports = [21, 22, 80, 443, 445, 3306, 3389, 8080]
        console.print(f"\n[warning][>] Début du scan sur {len(targets)} cible(s)...[/warning]")
        
        threads = []
        for ip in targets:
            for port in common_ports:
                t = Thread(target=self.check_port, args=(ip, port))
                t.start()
                threads.append(t)
                
                if len(threads) > 100:
                    for th in threads: th.join()
                    threads = []

        for t in threads: t.join()
        
        console.print("\n[warning]--- SCAN RÉSEAU TERMINÉ ---[/warning]")
        if not self.open_ports:
            console.print("[error][!] Aucun port ouvert trouvé sur la plage.[/error]")

class Traceroute:
    def __init__(self, target):
        self.target = target
        self.max_hops = 30
        self.timeout = 2.0

    def run(self):
        try:
            dest_addr = socket.gethostbyname(self.target)
        except socket.gaierror:
            console.print(f"[error][!] Impossible de résoudre l'hôte : {self.target}[/error]")
            return

        console.print(f"\n[warning][>] Traceroute vers {self.target} ({dest_addr}), {self.max_hops} sauts max :[/warning]\n")

        for ttl in range(1, self.max_hops + 1):
            curr_addr = None
            
            # Socket pour recevoir les messages ICMP (Time Exceeded)
            try:
                icmp_proto = socket.getprotobyname('icmp')
                udp_proto = socket.getprotobyname('udp')
                
                # Nécessite les privilèges root/admin
                rec_socket = socket.socket(socket.AF_INET, socket.SOCK_RAW, icmp_proto)
                send_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, udp_proto)
                
                send_socket.setsockopt(socket.SOL_IP, socket.IP_TTL, ttl)
                rec_socket.settimeout(self.timeout)
                rec_socket.bind(("", 33434))
                
                start_time = time.time()
                send_socket.sendto(b"", (dest_addr, 33434))
                
                _, curr_addr = rec_socket.recvfrom(512)
                curr_addr = curr_addr[0]
                duration = (time.time() - start_time) * 1000
                
            except socket.timeout:
                console.print(f"{ttl}\t * * * (Délai dépassé)")
                continue
            except PermissionError:
                console.print("[error][!] Traceroute nécessite les privilèges administrateur (sudo).[/error]")
                return
            finally:
                send_socket.close()
                rec_socket.close()

            if curr_addr:
                console.print(f"{ttl}\t {curr_addr}  {duration:.2f} ms")

            if curr_addr == dest_addr:
                console.print("\n[success][+] Destination atteinte.[/success]")
                break