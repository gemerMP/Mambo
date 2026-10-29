package app.mambo.next;
import android.app.*;
import android.content.*;
import android.net.VpnService;
import android.os.*;
import java.io.*;
import java.net.*;
import java.util.concurrent.*;
import org.json.*;
import hev.htproxy.TProxyService;
public final class Vpn extends VpnService {
 public static volatile String activeRaw="",status="Отключено";
 public static volatile boolean running,busy,verified;
 public static volatile long startedElapsed;
 public static final Traffic traffic=new Traffic();
 private static volatile Vpn current;
 private final ScheduledExecutorService worker=Executors.newSingleThreadScheduledExecutor();
 private NativeCore core;private ParcelFileDescriptor tunnel;private Data data;
 private volatile boolean closing;private boolean cleaned;private String stage="Подготовка";
 private ScheduledFuture<?> monitor;private volatile HttpProbe.Cancel healthCheck;
 @Override public void onCreate(){super.onCreate();data=new Data(this);current=this;}
 @Override public int onStartCommand(Intent intent,int flags,int startId){
  if(intent!=null&&"stop".equals(intent.getAction())){shutdown();return START_NOT_STICKY;}
  if(closing)return START_NOT_STICKY;
  foreground();
  if(!busy&&!running){busy=true;status="Подключение…";worker.execute(()->connect());}
  return START_NOT_STICKY;
 }
 void foreground(){
  NotificationManager manager=(NotificationManager)getSystemService(NOTIFICATION_SERVICE);
  manager.createNotificationChannel(new NotificationChannel("vpn","VPN-подключение",NotificationManager.IMPORTANCE_LOW));
  PendingIntent open=PendingIntent.getActivity(this,0,new Intent(this,MainActivity.class),PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT);
  PendingIntent stop=PendingIntent.getService(this,1,new Intent(this,Vpn.class).setAction("stop"),PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT);
  Notification n=new Notification.Builder(this,"vpn").setSmallIcon(R.drawable.icon).setContentTitle("Mambo Next").setContentText("VPN-служба · нажми, чтобы открыть приложение").setContentIntent(open).setOngoing(true).addAction(new Notification.Action.Builder(null,"Отключить",stop).build()).build();startForeground(1,n);
 }
 void connect(){
  try{
   JSONObject p=data.selected();if(p==null)throw new Exception("Нет выбранного сервера");activeRaw=p.getString("raw");
   data.log("Подключение · "+p.optString("protocol").toUpperCase(java.util.Locale.ROOT));
   stage="Запуск ядра";core=new NativeCore();core.start(this,data.config(p,10808));if(closing){cleanup();return;}
   stage="Создание VPN-интерфейса";int tunMtu=data.n("mtu",1500);
   if(p.optString("protocol").equals("wireguard"))tunMtu=Math.min(tunMtu,p.getJSONObject("outbound").getJSONObject("settings").optInt("mtu",1420));
   Builder b=new Builder().setSession("Mambo Next").setMtu(tunMtu).addAddress("10.66.0.1",30).addRoute("0.0.0.0",0);
   if(data.b("ipv6",true))b.addAddress("fd66:6d61:6d62::1",126).addRoute("::",0);
   for(String s:data.dns(p).split("[,\\s]+")){
    if(s.isEmpty())continue;if(!s.matches("[0-9a-fA-F:.]+"))throw new Exception("DNS должен быть IP");
    InetAddress ip=InetAddress.getByName(s);if(ip instanceof Inet4Address||data.b("ipv6",true))b.addDnsServer(ip);
   }
   b.addDisallowedApplication(getPackageName());b.setBlocking(false);tunnel=b.establish();if(tunnel==null)throw new Exception("Нет разрешения VPN");
   File config=new File(getFilesDir(),"tunnel.yml");
   try(FileOutputStream out=new FileOutputStream(config)){
    String yaml="tunnel:\n  mtu: "+tunMtu+"\n  ipv4: 10.66.0.1\n"+(data.b("ipv6",true)?"  ipv6: 'fd66:6d61:6d62::1'\n":"")+"socks5:\n  address: 127.0.0.1\n  port: 10808\n  udp: 'udp'\nmisc:\n  log-level: error\n";out.write(yaml.getBytes("UTF-8"));
   }
   stage="Запуск TUN/SOCKS";
   if(!TProxyService.TProxyStartService(config.getAbsolutePath(),tunnel.getFd()))throw new Exception("Не запустился туннель");
   if(closing){cleanup();return;}
   traffic.reset();startedElapsed=SystemClock.elapsedRealtime();verified=false;running=true;busy=false;status="Проверяем доступ…";
   data.log("TUN запущен · MTU "+tunMtu+" · IPv6 "+data.b("ipv6",true));
   monitor=worker.scheduleWithFixedDelay(()->{
    if(!closing&&(!core.running()||!TProxyService.TProxyIsRunning())){data.log("VPN: процесс остановился");shutdown();return;}
    if(!closing)sampleTraffic();
   },1,1,TimeUnit.SECONDS);
   checkAccess();
  }catch(Exception e){data.log("Ошибка VPN · этап: "+stage+" · "+Data.error(e));status="Ошибка: "+stage;closing=true;cleanup();stopSelf();}
 }
 void checkAccess(){
  HttpProbe.Cancel request=new HttpProbe.Cancel();healthCheck=request;
  try{
   for(String url:new String[]{"https://www.gstatic.com/generate_204","https://example.com/"}){
    if(closing)return;
    try{long ms=Diagnostics.https(new URL(url),10808,4000,request);if(closing)return;verified=true;status="Подключено";data.log("Доступ через VPN подтверждён · "+ms+" мс");return;}
    catch(Exception e){if(closing)return;data.log("Проверка доступа: "+Data.error(e));}
   }
   if(!closing){status="Нет ответа через VPN";data.log("TUN работает, доступ в интернет не подтверждён");if(activeRaw.toLowerCase(java.util.Locale.ROOT).contains("wireguard://")||activeRaw.toLowerCase(java.util.Locale.ROOT).startsWith("wg://")||activeRaw.toLowerCase(java.util.Locale.ROOT).contains("[interface]"))data.log("WireGuard: проверь UDP до Endpoint, ключи, PSK, Reserved и AllowedIPs. Попробуй MTU 1280 в маршрутизации.");}
  }finally{healthCheck=null;}
 }
 void sampleTraffic(){try{traffic.add(core.traffic());}catch(Exception e){data.log("Счётчик трафика временно недоступен");}}
 public void shutdown(){if(closing)return;closing=true;busy=true;status="Отключение…";HttpProbe.Cancel request=healthCheck;if(request!=null)request.stop();worker.execute(()->{cleanup();stopSelf();});}
 void cleanup(){
  if(cleaned)return;cleaned=true;if(monitor!=null)monitor.cancel(false);
  long elapsed=startedElapsed>0?(SystemClock.elapsedRealtime()-startedElapsed)/1000:0;
  if(core!=null&&running)sampleTraffic();
  try{if(current==this)TProxyService.TProxyStopService();}catch(Throwable ignored){}
  if(core!=null)core.stop();
  if(tunnel!=null){try{tunnel.close();}catch(IOException ignored){}tunnel=null;}
  if(current==this){running=false;busy=false;verified=false;activeRaw="";startedElapsed=0;traffic.uploadRate=traffic.downloadRate=0;if(!status.startsWith("Ошибка"))status="Отключено";}
  data.log("VPN остановлен · "+elapsed+" с · загружено "+traffic.downloaded+" Б · выгружено "+traffic.uploaded+" Б");stopForeground(STOP_FOREGROUND_REMOVE);
 }
 @Override public void onRevoke(){shutdown();super.onRevoke();}
 @Override public void onDestroy(){closing=true;HttpProbe.Cancel request=healthCheck;if(request!=null)request.stop();try{worker.execute(()->cleanup());}catch(RejectedExecutionException ignored){}worker.shutdown();super.onDestroy();}
}
