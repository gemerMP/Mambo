package app.mambo.next;
import android.content.Context;import org.json.*;import java.net.*;import java.io.*;import java.util.concurrent.*;import java.util.regex.*;
public final class Probe {
 public static String measure(Context c,JSONObject p,Data data,HttpProbe.Cancel cancel)throws Exception{return measure(c,p,data,cancel,data.n("pingType",0),data.n("pingMode",0));}
 public static String measure(Context c,JSONObject p,Data data,HttpProbe.Cancel cancel,int type,int mode)throws Exception{
  p=Profiles.parse(p.getString("raw"));cancel.check();int timeout=data.n("timeout",8)*1000;String host=p.getString("host");long ms;
  if(type==2){if(p.getString("protocol").equals("wireguard"))return "TCP неприменим: WireGuard использует UDP";try(Socket socket=new Socket()){cancel.socket=socket;long start=System.nanoTime();socket.connect(new InetSocketAddress(host,p.getInt("port")),timeout);ms=Math.max(1,(System.nanoTime()-start)/1000000);}finally{cancel.socket=null;}return ms+" мс · TCP";}
  if(type==3){Process process=new ProcessBuilder("/system/bin/ping",host.contains(":")?"-6":"-4","-n","-c","1","-W",String.valueOf(timeout/1000),host).redirectErrorStream(true).start();cancel.process=process;try{if(!process.waitFor(timeout+1000,TimeUnit.MILLISECONDS)){process.destroy();throw new SocketTimeoutException();}cancel.check();String output=Data.read(process.getInputStream());Matcher m=Pattern.compile("time[=<]\\s*([0-9.]+)").matcher(output);if(process.exitValue()!=0||!m.find())return "ICMP недоступен или заблокирован";return m.group(1)+" мс · ICMP";}finally{process.destroy();cancel.process=null;}}
  URL url=new URL(data.s("testUrl","https://www.gstatic.com/generate_204"));if(!url.getProtocol().equals("https")||url.getUserInfo()!=null||url.toString().matches(".*[\\r\\n ].*"))throw new IOException("Нужен корректный HTTPS URL теста");String method=type==1?"HEAD":"GET";boolean reuse=Vpn.running&&p.getString("raw").equals(Vpn.activeRaw);if(p.getString("protocol").equals("wireguard")&&(Vpn.busy||(Vpn.running&&!reuse)))throw new IOException("WireGuard: отключи VPN перед проверкой другого профиля");NativeCore core=null;int port=reuse?10808:0;long best=Long.MAX_VALUE;Exception failure=null;
  try{for(int round=0;round<(mode==0?1:2);round++){cancel.check();if(!reuse&&core==null){try(ServerSocket local=new ServerSocket(0,1,InetAddress.getByName("127.0.0.1"))){port=local.getLocalPort();}core=new NativeCore();core.start(c,data.probeConfig(p,port));}
    try(HttpProbe http=new HttpProbe(cancel,timeout)){long start=http.connect(url,port);long first=http.request(method,mode==2,start);if(mode==2){long second=http.request(method,false,0);return second+" мс · "+method+" KeepAlive (2-й запрос)";}best=Math.min(best,first);}catch(Exception e){failure=e;if(mode==2)throw e;}
    if(mode==0&&core!=null){core.stop();core=null;}
   }if(best==Long.MAX_VALUE)throw failure==null?new IOException("Нет ответа"):failure;return best+" мс · "+method+(mode==0?"":" · лучший из 2");
  }finally{if(core!=null)core.stop();}
 }
}
