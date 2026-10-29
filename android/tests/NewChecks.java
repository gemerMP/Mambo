package app.mambo.next;
import java.net.URL;
public final class NewChecks {
 static void require(boolean value,String name){if(!value)throw new AssertionError(name);}
 public static void main(String[] args)throws Exception{
  Traffic t=new Traffic();t.reset();t.add("proxy,uplink,1024;proxy,downlink,2048;direct,downlink,999;broken;proxy,uplink,-5;");require(t.uploaded==1024&&t.downloaded==2048,"counter directions and direct exclusion");t.add("proxy,uplink,7;proxy,downlink,9;");require(t.uploaded==1031&&t.downloaded==2057,"accumulate deltas");require(Traffic.bytes(2048).equals("2.0 КиБ"),"units");require(Traffic.duration(90061).equals("25:01:01"),"duration does not wrap");require(Diagnostics.comparison(false,false).contains("причину определить нельзя"),"no false DPI assertion");
  if(args.length>0){int port=Integer.parseInt(args[0]);for(int type:new int[]{1,28})require(Diagnostics.dns(port,args[1],"vpn.test",5000,new HttpProbe.Cancel(),type).contains("UDP проходит"),"real DNS response over SOCKS/WG");require(Diagnostics.https(new URL(args[2]),0,5000,new HttpProbe.Cancel())>0,"direct HTTPS path");}
  System.out.println("PASS Java traffic accumulation, DNS/UDP and direct HTTPS checks");
 }
}
