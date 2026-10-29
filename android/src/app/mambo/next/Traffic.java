package app.mambo.next;
import java.util.Locale;
/** Xray's JNI returns deltas and resets counters; accumulate exactly once in VPN worker. */
public final class Traffic {
 public volatile long uploaded,downloaded; public volatile double uploadRate,downloadRate; private long last;
 public void reset(){uploaded=downloaded=0;uploadRate=downloadRate=0;last=System.nanoTime();}
 public synchronized void add(String values){long up=0,down=0;for(String item:values.split(";")){String[] a=item.split(",");if(a.length!=3||!a[0].equals("proxy"))continue;try{long n=Math.max(0,Long.parseLong(a[2]));if(a[1].equals("uplink"))up+=n;else if(a[1].equals("downlink"))down+=n;}catch(NumberFormatException ignored){}}long now=System.nanoTime();double sec=Math.max(.01,(now-last)/1e9);uploaded+=up;downloaded+=down;uploadRate=up/sec;downloadRate=down/sec;last=now;}
 public static String bytes(double v){v=Math.max(0,v);String[] units={"Б","КиБ","МиБ","ГиБ","ТиБ"};int i=0;while(v>=1024&&i<4){v/=1024;i++;}return (i==0?String.valueOf((long)v):String.format(Locale.ROOT,"%.1f",v))+" "+units[i];}
 public static String duration(long seconds){seconds=Math.max(0,seconds);return String.format(Locale.ROOT,"%02d:%02d:%02d",seconds/3600,(seconds%3600)/60,seconds%60);}
}
