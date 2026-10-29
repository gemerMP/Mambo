package app.mambo.next;
import java.net.*;
public final class NetworkProbe {
 public static void main(String[] args)throws Exception{
  int socks=Integer.parseInt(args[0]);URL target=new URL(args[1]);HttpProbe.Cancel cancel=new HttpProbe.Cancel();
  try(HttpProbe p=new HttpProbe(cancel,5000)){long start=p.connect(target,socks);p.request("GET",true,start);p.request("GET",false,0);}
  try(HttpProbe p=new HttpProbe(cancel,5000)){long start=p.connect(target,socks);p.request("HEAD",true,start);p.request("HEAD",false,0);}
  System.out.println("PASS: GET and HEAD through Xray SOCKS → VPN → TLS; two requests per TLS connection");
 }
}
