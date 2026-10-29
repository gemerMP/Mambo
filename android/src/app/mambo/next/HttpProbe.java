package app.mambo.next;
import java.io.*;import java.net.*;import java.nio.charset.StandardCharsets;import java.util.*;import javax.net.ssl.*;
/** HTTP/1.1 probe with bounded parsing and a real reusable TLS connection. */
public final class HttpProbe implements AutoCloseable {
 public static final class Cancel {public volatile boolean cancelled;volatile Socket socket;volatile Process process;volatile DatagramSocket datagram;public void stop(){cancelled=true;try{if(socket!=null)socket.close();}catch(IOException ignored){}if(process!=null)process.destroy();if(datagram!=null)datagram.close();}public void check()throws IOException{if(cancelled)throw new IOException("Отменено");}}
 private final Cancel cancel;private final int timeout;private Socket socket;private InputStream in;private OutputStream out;private URL url;private long deadline;
 public HttpProbe(Cancel c,int millis){cancel=c;timeout=millis;}
 private void remaining()throws IOException{cancel.check();long ms=(deadline-System.nanoTime())/1000000;if(ms<=0)throw new SocketTimeoutException();socket.setSoTimeout((int)Math.min(ms,Integer.MAX_VALUE));}
 private int one()throws IOException{remaining();int b=in.read();if(b<0)throw new EOFException("Прокси закрыл соединение");return b;}
 private void bytes(int n)throws IOException{for(int i=0;i<n;i++)one();}
 public long connect(URL u,int proxyPort)throws Exception{
  if(!u.getProtocol().equals("https")||u.getUserInfo()!=null||u.toString().matches(".*[\\r\\n ].*"))throw new IOException("Нужен корректный HTTPS URL теста");
  url=u;long start=System.nanoTime();deadline=start+timeout*1000000L;
  String hostname=u.getHost();if(hostname.startsWith("["))hostname=hostname.substring(1,hostname.length()-1);
  int port=u.getPort()<0?443:u.getPort();socket=new Socket();cancel.socket=socket;cancel.check();
  socket.connect(new InetSocketAddress(proxyPort>0?"127.0.0.1":hostname,proxyPort>0?proxyPort:port),timeout);
  in=socket.getInputStream();out=socket.getOutputStream();
  if(proxyPort>0){
   out.write(new byte[]{5,1,0});out.flush();if(one()!=5||one()!=0)throw new IOException("Ошибка SOCKS-аутентификации");
   byte[] host=IDN.toASCII(hostname).getBytes(StandardCharsets.UTF_8);if(host.length>255)throw new IOException("Слишком длинный хост");
   out.write(new byte[]{5,1,0,3,(byte)host.length});out.write(host);out.write(new byte[]{(byte)(port>>8),(byte)port});out.flush();
   if(one()!=5||one()!=0)throw new IOException("Сервер не пропускает тестовый запрос");one();int kind=one();
   if(kind==1)bytes(4);else if(kind==4)bytes(16);else if(kind==3)bytes(one());else throw new IOException("Некорректный SOCKS-ответ");bytes(2);
  }
  SSLSocket tls=(SSLSocket)((SSLSocketFactory)SSLSocketFactory.getDefault()).createSocket(socket,hostname,port,true);socket=tls;cancel.socket=tls;
  SSLParameters params=tls.getSSLParameters();params.setEndpointIdentificationAlgorithm("HTTPS");tls.setSSLParameters(params);remaining();tls.startHandshake();in=tls.getInputStream();out=tls.getOutputStream();return start;
 }
 public long request(String method,boolean reuse,long start)throws Exception{if(start==0){start=System.nanoTime();deadline=start+timeout*1000000L;}remaining();String path=url.getFile();if(path.isEmpty())path="/";String host=url.getHost()+(url.getPort()>0?":"+url.getPort():"");String req=method+" "+path+" HTTP/1.1\r\nHost: "+host+"\r\nUser-Agent: MamboNext/0.9.3\r\nAccept: */*\r\nAccept-Encoding: identity\r\nConnection: "+(reuse?"keep-alive":"close")+"\r\n\r\n";out.write(req.getBytes(StandardCharsets.US_ASCII));out.flush();InputStream timed=new FilterInputStream(in){public int read()throws IOException{remaining();return super.read();}public int read(byte[] b,int off,int len)throws IOException{remaining();return super.read(b,off,len);}};
  Response response=readResponse(timed,method);long elapsed=Math.max(1,(System.nanoTime()-start)/1000000);if(response.status<200||response.status>=400)throw new IOException("URL теста вернул HTTP "+response.status);if(reuse&&!response.reusable)throw new IOException("URL теста не поддерживает KeepAlive");return elapsed;
 }
 public void close(){try{if(socket!=null)socket.close();}catch(IOException ignored){}if(cancel.socket==socket)cancel.socket=null;}
 public static final class Response {public final int status;public final boolean reusable;Response(int code,boolean reuse){status=code;reusable=reuse;}}
 static String line(InputStream in,int max)throws IOException{ByteArrayOutputStream b=new ByteArrayOutputStream();int c;while((c=in.read())!=-1){if(c=='\n')return new String(b.toByteArray(),StandardCharsets.US_ASCII).replace("\r","");if(b.size()>=max)throw new IOException("Заголовок HTTP слишком большой");b.write(c);}throw new EOFException("Неполный HTTP-ответ");}
 static void skip(InputStream in,long count)throws IOException{if(count<0||count>524288)throw new IOException("Ответ URL больше 512 КБ; выбери /generate_204");byte[] b=new byte[4096];while(count>0){int n=in.read(b,0,(int)Math.min(b.length,count));if(n<0)throw new EOFException("Неполное тело HTTP");count-=n;}}
 public static Response readResponse(InputStream in,String method)throws IOException{
  String first=line(in,8192);String[] parts=first.split(" ",3);if(parts.length<2||!parts[0].startsWith("HTTP/1."))throw new IOException("Некорректный HTTP-ответ");int status;try{status=Integer.parseInt(parts[1]);}catch(Exception e){throw new IOException("Некорректный статус HTTP");}Map<String,String> headers=new HashMap<>();int size=first.length();while(true){String l=line(in,8192);if(l.isEmpty())break;size+=l.length();if(size>32768)throw new IOException("Заголовки HTTP больше 32 КБ");int colon=l.indexOf(':');if(colon<1)throw new IOException("Некорректный заголовок HTTP");String k=l.substring(0,colon).toLowerCase(Locale.ROOT),v=l.substring(colon+1).trim();if(headers.containsKey(k)&&k.equals("content-length")&&!headers.get(k).equals(v))throw new IOException("Противоречивый Content-Length");headers.put(k,v);}
  if(status<200)throw new IOException("Промежуточный HTTP-ответ не поддерживается");boolean reuse=parts[0].equals("HTTP/1.1")&&!headers.getOrDefault("connection","").toLowerCase(Locale.ROOT).contains("close");if(method.equals("HEAD")||status==204||status==304)return new Response(status,reuse);
  String transfer=headers.get("transfer-encoding");if(transfer!=null){if(!transfer.equalsIgnoreCase("chunked"))throw new IOException("Неподдерживаемое кодирование HTTP");long total=0;while(true){String chunk=line(in,128).split(";",2)[0];long n;try{n=Long.parseLong(chunk.trim(),16);}catch(Exception e){throw new IOException("Некорректный chunk");}if(n<0||n>524288-total)throw new IOException("Ответ URL больше 512 КБ");if(n==0){int trailers=0;while(true){String l=line(in,8192);if(l.isEmpty())break;trailers+=l.length();if(trailers>32768)throw new IOException("Слишком много trailer-заголовков");}break;}skip(in,n);total+=n;if(in.read()!='\r'||in.read()!='\n')throw new IOException("Некорректный chunk");}}
  else if(headers.containsKey("content-length")){long len;try{len=Long.parseLong(headers.get("content-length"));}catch(Exception e){throw new IOException("Некорректная длина HTTP");}skip(in,len);}else {reuse=false;int n,total=0;byte[] b=new byte[4096];while((n=in.read(b))!=-1){total+=n;if(total>524288)throw new IOException("Ответ URL больше 512 КБ");}}
  return new Response(status,reuse);
 }
}
