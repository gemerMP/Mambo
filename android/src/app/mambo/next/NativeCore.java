package app.mambo.next;
import android.content.Context;
import libv2ray.*;
import org.json.*;
import java.net.*;
import java.util.*;
public final class NativeCore {
 private static boolean initialized;
 private CoreController controller;
 private static final Set<String> usedWG=new HashSet<>();
 private final List<String> ownedWG=new ArrayList<>();
 public static synchronized void initialize(Context context)throws Exception{
  if(!initialized){go.Seq.setContext(context.getApplicationContext());Libv2ray.initCoreEnv(context.getFilesDir().getAbsolutePath(),"");initialized=true;}
 }
 public void start(Context c,String config)throws Exception{
  initialize(c);
  JSONObject parsed=new JSONObject(config);
  JSONArray outs=parsed.optJSONArray("outbounds");
  Data data=new Data(c);
  // Resolve the outer peer on the physical network before TUN exists. Never change stored profiles.
  if(outs!=null)for(int i=0;i<outs.length();i++){
   JSONObject o=outs.getJSONObject(i);
   if(!o.optString("protocol").equals("wireguard"))continue;
   JSONArray peers=o.getJSONObject("settings").getJSONArray("peers");
   for(int j=0;j<peers.length();j++){
    JSONObject peer=peers.getJSONObject(j);URI u=new URI("udp://"+peer.getString("endpoint"));
    String host=u.getHost();if(host.startsWith("["))host=host.substring(1,host.length()-1);
    InetAddress[] candidates=InetAddress.getAllByName(host);
    Arrays.sort(candidates,(a,b)->Boolean.compare(!(a instanceof Inet4Address),!(b instanceof Inet4Address)));
    InetAddress chosen=null;
    for(InetAddress address:candidates)try(DatagramSocket route=new DatagramSocket()){
     route.connect(address,u.getPort());chosen=address;break;
    }catch(Exception ignored){}
    if(chosen==null)throw new Exception("WireGuard: нет маршрута к Endpoint");
    String ip=chosen.getHostAddress();peer.put("endpoint",(chosen instanceof Inet6Address?"["+ip+"]":ip)+":"+u.getPort());
    data.log("WireGuard: Endpoint разрешён до TUN · "+(chosen instanceof Inet6Address?"IPv6":"IPv4"));
   }
  }
  synchronized(usedWG){
   if(outs!=null)for(int i=0;i<outs.length();i++){
    JSONObject o=outs.getJSONObject(i);
    if(o.optString("protocol").equals("wireguard")){
     String k=o.getJSONObject("settings").getString("secretKey");
     if(usedWG.contains(k))throw new Exception("WireGuard: этот ключ уже используется активным туннелем");ownedWG.add(k);
    }
   }
   usedWG.addAll(ownedWG);
  }
  try{
   controller=Libv2ray.newCoreController(new CoreCallbackHandler(){
    public long startup(){return 0;} public long shutdown(){return 0;}
    public long onEmitStatus(long code,String message){
     if(code!=0)data.log("Ядро: событие "+code+" · "+coreReason(message));return 0;
    }
   });
   controller.startLoop(parsed.toString(),0);
   if(!controller.getIsRunning())throw new Exception("Ядро не запустилось");
  }catch(Exception e){stop();throw e;}
 }
 static String coreReason(String message){String m=message==null?"":message.toLowerCase(Locale.ROOT);if(m.contains("handshake"))return "ошибка согласования";if(m.contains("timeout")||m.contains("deadline"))return "тайм-аут сети";if(m.contains("network is unreachable")||m.contains("no route"))return "нет сетевого маршрута";if(m.contains("dns")||m.contains("lookup"))return "ошибка DNS";if(m.contains("certificate")||m.contains("x509"))return "ошибка сертификата TLS";return "изменение состояния";}
 public boolean running(){return controller!=null&&controller.getIsRunning();}
 public String traffic(){return controller==null?"":controller.queryAllOutboundTrafficStats();}
 public void stop(){if(controller!=null){try{controller.stopLoop();}catch(Exception ignored){}controller=null;}synchronized(usedWG){usedWG.removeAll(ownedWG);ownedWG.clear();}}
}
