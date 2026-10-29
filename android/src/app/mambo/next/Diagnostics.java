package app.mambo.next;
import android.content.Context;
import org.json.*;
import java.io.*;
import java.net.*;
import java.util.*;
/** Measurements distinguish failed requests from confirmed censorship. */
public final class Diagnostics {
 public static final String[] MODES={"Доступ и возможная фильтрация","DNS через VPN · UDP","Стабильность · 5 HTTPS-запросов","WireGuard · параметры и доступ"};
 public static long https(URL url,int port,int timeout,HttpProbe.Cancel cancel)throws Exception{try(HttpProbe http=new HttpProbe(cancel,timeout)){long start=http.connect(url,port);return http.request("GET",false,start);}}
 public static String comparison(boolean direct,boolean proxy){if(proxy&&!direct)return "Через прокси ответ есть, напрямую — нет. Возможны фильтрация или сбой прямого маршрута.";if(direct&&!proxy)return "Напрямую доступ есть. Проверь VPN-сервер и правила.";if(direct)return "Оба пути отвечают. Признаков ограничения для этого адреса не обнаружено.";return "Оба пути не отвечают. По этому тесту причину определить нельзя.";}
 static int one(InputStream in)throws Exception{int b=in.read();if(b<0)throw new EOFException();return b;}
 static void skip(InputStream in,int count)throws Exception{for(int i=0;i<count;i++)one(in);}
 public static String dns(int port,String server,String host,int timeout,HttpProbe.Cancel cancel,int type)throws Exception{
  try(Socket control=new Socket()){
   cancel.socket=control;cancel.check();control.connect(new InetSocketAddress("127.0.0.1",port),timeout);control.setSoTimeout(timeout);
   InputStream in=control.getInputStream();OutputStream out=control.getOutputStream();out.write(new byte[]{5,1,0});out.flush();if(one(in)!=5||one(in)!=0)throw new IOException("Ошибка SOCKS");out.write(new byte[]{5,3,0,1,0,0,0,0,0,0});out.flush();if(one(in)!=5||one(in)!=0)throw new IOException("UDP ASSOCIATE недоступен");one(in);int kind=one(in);byte[] address=new byte[kind==1?4:kind==4?16:kind==3?one(in):0];if(address.length==0)throw new IOException("Некорректный UDP-адрес");for(int i=0;i<address.length;i++)address[i]=(byte)one(in);String relay=kind==3?new String(address,"US-ASCII"):InetAddress.getByAddress(address).getHostAddress();if(relay.equals("0.0.0.0")||relay.equals("0:0:0:0:0:0:0:0"))relay="127.0.0.1";int relayPort=(one(in)<<8)|one(in);
   byte[] target=InetAddress.getByName(server).getAddress();int id=new Random().nextInt(65536);ByteArrayOutputStream bytes=new ByteArrayOutputStream();DataOutputStream query=new DataOutputStream(bytes);query.write(new byte[]{0,0,0,(byte)(target.length==4?1:4)});query.write(target);query.writeShort(53);query.writeShort(id);query.writeShort(0x100);query.writeShort(1);query.write(new byte[6]);for(String label:IDN.toASCII(host).split("\\.")){byte[] encoded=label.getBytes("US-ASCII");if(encoded.length<1||encoded.length>63)throw new IOException("Некорректное DNS-имя");query.writeByte(encoded.length);query.write(encoded);}query.writeByte(0);query.writeShort(type);query.writeShort(1);
   try(DatagramSocket udp=new DatagramSocket()){
    cancel.datagram=udp;cancel.check();udp.connect(InetAddress.getByName(relay),relayPort);udp.setSoTimeout(timeout);byte[] data=bytes.toByteArray();udp.send(new DatagramPacket(data,data.length));byte[] response=new byte[65535];DatagramPacket packet=new DatagramPacket(response,response.length);udp.receive(packet);cancel.check();int length=packet.getLength();if(length<10||response[0]!=0||response[1]!=0||response[2]!=0)throw new IOException("Некорректный UDP-ответ");int off=response[3]==1?10:response[3]==4?22:response[3]==3?7+(response[4]&255):length;if(length<off+12||((response[off]&255)<<8|(response[off+1]&255))!=id||(response[off+2]&128)==0)throw new IOException("Некорректный DNS-ответ");int code=response[off+3]&15,answers=(response[off+6]&255)<<8|(response[off+7]&255);return "DNS "+(type==1?"A":"AAAA")+": RCODE "+code+", ответов "+answers+(code==0&&answers>0?" · UDP проходит":" · UDP отвечает, записи не получены");
   }finally{cancel.datagram=null;}
  }finally{cancel.socket=null;}
 }
 public static String run(Context context,JSONObject stored,Data data,int mode,HttpProbe.Cancel cancel)throws Exception{
  JSONObject profile=Profiles.parse(stored.getString("raw"));boolean reuse=Vpn.running&&profile.getString("raw").equals(Vpn.activeRaw);if(Vpn.busy)throw new IOException("Подожди завершения подключения");if(profile.optString("protocol").equals("wireguard")&&Vpn.running&&!reuse)throw new IOException("WireGuard: отключи VPN перед проверкой другого профиля");
  int port=reuse?10808:0,timeout=Math.min(15,data.n("timeout",8))*1000;NativeCore owned=null;StringBuilder result=new StringBuilder(MODES[mode]).append('\n');
  try{
   if(!reuse){try(ServerSocket local=new ServerSocket(0,1,InetAddress.getByName("127.0.0.1"))){port=local.getLocalPort();}cancel.check();owned=new NativeCore();owned.start(context,data.probeConfig(profile,port));}
   URL url=new URL(data.s("testUrl","https://www.gstatic.com/generate_204"));
   if(mode==0){
    LinkedHashSet<String> targets=new LinkedHashSet<>(Arrays.asList(url.toString(),"https://example.com/"));
    for(String value:targets){URL target=new URL(value);result.append('\n').append(target.getHost()).append('\n');boolean direct=false,proxy=false;for(int i=0;i<2;i++){cancel.check();try{long ms=https(target,i==0?0:port,timeout,cancel);result.append(i==0?"Напрямую: ":"Через прокси: ").append(ms).append(" мс · HTTPS проходит\n");if(i==0)direct=true;else proxy=true;}catch(Exception e){cancel.check();result.append(i==0?"Напрямую: ":"Через прокси: ").append(Data.error(e)).append('\n');}}result.append(comparison(direct,proxy)).append('\n');}
    result.append("\nСам Mambo исключён из Android VPN. Проверка через прокси учитывает правила маршрутизации. Сравнение не доказывает наличие или отсутствие DPI.");
   }else if(mode==1){int n=0;for(String server:data.dns(profile).split("[,\\s]+")){if(server.isEmpty()||n++>=2)continue;for(int type:new int[]{1,28}){cancel.check();try{result.append(server).append(" · ").append(dns(port,server,"example.com",timeout,cancel,type)).append('\n');}catch(Exception e){cancel.check();result.append(server).append(" · ").append(Data.error(e)).append('\n');}}}
   }else if(mode==2){ArrayList<Long> samples=new ArrayList<>();for(int i=0;i<5;i++){cancel.check();result.append(i+1).append(". ");try{long ms=https(url,port,timeout,cancel);samples.add(ms);result.append(ms).append(" мс\n");}catch(Exception e){cancel.check();result.append(Data.error(e)).append('\n');}}result.append("Успешно ").append(samples.size()).append("/5 · ошибок запросов ").append((5-samples.size())*20).append("%\n");if(!samples.isEmpty()){long sum=0,jitter=0;for(int i=0;i<samples.size();i++){sum+=samples.get(i);if(i>0)jitter+=Math.abs(samples.get(i)-samples.get(i-1));}result.append("Мин/среднее/макс: ").append(Collections.min(samples)).append('/').append(sum/samples.size()).append('/').append(Collections.max(samples)).append(" мс\n");if(samples.size()>1)result.append("Разброс соседних успешных запросов: ").append(jitter/(samples.size()-1)).append(" мс\n");}result.append("Это HTTPS-запросы; процент ошибок не равен потерям IP-пакетов.");
   }else{
    if(!profile.optString("protocol").equals("wireguard"))throw new IOException("WireGuard: выбери профиль WireGuard");JSONObject wg=profile.getJSONObject("outbound").getJSONObject("settings");result.append("Пиров: ").append(wg.getJSONArray("peers").length()).append(" · MTU ").append(Math.min(wg.optInt("mtu",1420),data.n("mtu",1500))).append('\n');result.append(reuse?"Используется активный туннель. Второй не создаётся.\n":"Проверка через изолированное ядро.\n");
    try{long ms=https(url,port,timeout,cancel);result.append("Ответ через WireGuard: ").append(ms).append(" мс · HTTPS проходит");}catch(Exception e){cancel.check();result.append("Нет подтверждённого ответа: ").append(Data.error(e)).append("\nПроверь UDP до Endpoint, ключи, PSK и Reserved. Попробуй MTU 1280 в маршрутизации. Проверь, что DNS входит в AllowedIPs. Успех TCP-пинга не подтверждает работу WireGuard.");}
   }
   return result.toString();
  }finally{if(owned!=null)owned.stop();}
 }
}
