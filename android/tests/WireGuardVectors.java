package app.mambo.next;
import org.json.*;import java.nio.file.*;
public class WireGuardVectors {
 public static void main(String[] args)throws Exception{JSONArray cases=new JSONArray(new String(Files.readAllBytes(Paths.get(args[0])),"UTF-8"));for(int i=0;i<cases.length();i++){JSONObject c=cases.getJSONObject(i);try{Profiles.parse(c.getString("raw"));if(!c.getBoolean("valid"))throw new AssertionError(c.getString("name")+" incorrectly accepted");}catch(Exception e){if(c.getBoolean("valid"))throw new AssertionError(c.getString("name")+": "+e.getMessage());}}System.out.println("PASS: "+cases.length()+" shared WireGuard vectors (Java)");}
}
