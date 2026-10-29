package app.mambo.next;
import java.nio.file.*;
public final class BuildFixture {
 public static void main(String[] args)throws Exception{String raw=new String(Files.readAllBytes(Paths.get(args[0])),"UTF-8");org.json.JSONObject p=Profiles.parse(raw);String config=Profiles.config(p,Integer.parseInt(args[1]),"","","","proxy",p.optString("dns","").isEmpty()?"1.1.1.1":p.getString("dns"));Files.write(Paths.get(args[2]),config.getBytes("UTF-8"));}
}
