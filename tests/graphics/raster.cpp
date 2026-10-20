#include "VBT_RASTER_SIM.h"
#include "verilated.h"
#include "mame_scanline.h"
#include <array>
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <iostream>
#include <fstream>
#include <filesystem>
#include <iomanip>
#include <sstream>
#include <stdexcept>
#include <vector>

struct Raster {
    VerilatedContext ctx;
    VBT_RASTER_SIM top{&ctx};
    MameScanline oracle;
    std::array<std::vector<uint8_t>,2> fg;
    std::array<std::vector<uint16_t>,2> bg;
    Palette palette;
    bitmap_rgb32 bitmap;
    uint64_t cycles=0,pixels=0,mismatches=0;
    unsigned frame=0,x=0,lines=0,refresh_age=0;
    bool rendering=false,prev_h=false,prev_v=false,ref_active=false;
    uint32_t last_ref=0;
    std::array<uint32_t,512> expected;
    std::vector<uint32_t> captured_actual,captured_expected;
    unsigned heblnk=64;
    struct DisplayEvent {unsigned v,h,display,scroll0,scroll1,address;};
    std::vector<DisplayEvent> display_events;
    unsigned next_event=0,event_age=0,previous_vcount=0;
    Raster() {
        for(auto& v:fg)v.resize(262144);
        for(auto& v:bg)v.resize(262144);
        oracle.m_vram_bg[0]=bg[0].data();oracle.m_vram_bg[1]=bg[1].data();
        oracle.m_tlc34076=&palette;
        top.RST_N=0;top.BUS_RAS_N=1;top.BUS_WE_N=1;top.BUS_QE_N=1;top.BUS_CAS_N=15;
        tick(8);top.RST_N=1;tick(8);
    }
    void sample(bool ce,bool h,bool v,uint32_t rgb) {
        if(!rendering || !ce)return;
        if(!prev_v && v)++frame;
        if(v && h) {
            if(!prev_h) {
                x=0;
                Params p{last_ref>>16,last_ref&65535,heblnk,heblnk+512};
                oracle.draw(bitmap,0,&p);
                for(unsigned i=0;i<512;i++)expected[i]=bitmap.data[heblnk+i]&0xffffff;
            }
            if(frame>=2) {
                if(x>=512)throw std::runtime_error("more than 512 active pixels");
                if(rgb!=expected[x]) {
                    if(mismatches<4)std::cerr<<"raster mismatch frame="<<frame<<" line="<<lines<<" x="<<x
                        <<" ref="<<std::hex<<last_ref<<" expected="<<expected[x]<<" actual="<<rgb<<std::dec<<'\n';
                    ++mismatches;
                }
                ++pixels;
                if(frame==2) {captured_actual.push_back(rgb);captured_expected.push_back(expected[x]);}
            }
            ++x;
        }
        if(prev_h && !h && v && x) {
            if(frame>=2 && x!=512)throw std::runtime_error("wrong active line width");
            ++lines;
        }
        prev_h=h;prev_v=v;
    }
    void tick(unsigned n=1) {
        while(n--) {
            top.CLK=0;top.CLK2X=0;top.eval();ctx.timeInc(1);
            if(rendering && !display_events.empty()) {
                if(top.VCOUNT<previous_vcount)next_event=0;
                previous_vcount=top.VCOUNT;
                if(event_age && ++event_age>12) {
                    event_age=0;top.BUS_RAS_N=1;top.BUS_WE_N=1;top.BUS_CAS_N=15;
                }
                if(!event_age && next_event<display_events.size()) {
                    const auto& e=display_events[next_event];
                    if(top.VCOUNT==e.v && top.HCOUNT>=e.h) {
                        if(ref_active)throw std::runtime_error("display write overlaps a refresh transaction");
                        // A trace row includes the complete merged display state.
                        // Only the changed register needs a real CPU transaction.
                        uint32_t address=e.address;
                        uint32_t data=address==0x20000200?e.scroll0:
                                      address==0x20000280?e.scroll1:e.display;
                        top.BUS_ADDR=(address&~15u)|8;top.BUS_BIT_ADDR=address;top.BUS_DATA=data;
                        top.BUS_RAS_N=0;top.BUS_WE_N=0;top.BUS_QE_N=1;top.BUS_CAS_N=12;
                        oracle.m_screen_control=(e.display>>8)&3;
                        oracle.m_vram_fg_display=fg[(e.display&0x8000)?0:1].data();
                        oracle.m_xscroll[0]=e.scroll0&255;oracle.m_yscroll[0]=e.scroll0>>8;
                        oracle.m_xscroll[1]=e.scroll1&255;oracle.m_yscroll[1]=e.scroll1>>8;
                        event_age=1;++next_event;
                    }
                }
            }
            bool ce=top.MIX_CE,h=top.HBL_N,v=top.VBL_N;uint32_t rgb=top.RGB;
            bool ref=rendering && top.REF_RUN && !ref_active;
            uint32_t a=top.REF_ADDR;
            top.CLK=1;top.CLK2X=1;top.eval();ctx.timeInc(1);
            sample(ce,h,v,rgb);
            if(ref) {
                ref_active=true;refresh_age=0;last_ref=a;
                top.BUS_BIT_ADDR=a;top.BUS_ADDR=(a&~15u)|4;
                top.BUS_RAS_N=0;top.BUS_QE_N=0;top.BUS_WE_N=1;top.BUS_CAS_N=15;
            }
            if(ref_active && ++refresh_age>=700) {
                if(!top.READY)throw std::runtime_error("scanline prefill missed the blanking deadline");
                top.BUS_RAS_N=1;top.BUS_QE_N=1;ref_active=false;
            }
            top.CLK2X=0;top.eval();ctx.timeInc(1);
            top.CLK=0;top.CLK2X=1;top.eval();ctx.timeInc(1);
            ++cycles;
        }
    }
    void write(uint32_t a,uint32_t data,uint8_t cas=0) {
        top.BUS_RAS_N=1;top.BUS_WE_N=1;top.BUS_QE_N=1;tick(8);
        top.BUS_ADDR=(a&~15u)|8;top.BUS_BIT_ADDR=a;top.BUS_DATA=data;
        top.BUS_RAS_N=0;top.BUS_WE_N=0;top.BUS_CAS_N=cas;tick(12);
        top.BUS_RAS_N=1;top.BUS_WE_N=1;top.BUS_CAS_N=15;tick(8);
    }
    void io(unsigned a,uint32_t d) {
        top.IO_A=a;top.IO_DI=d;top.IO_WE=1;tick(10);top.IO_WE=0;tick(5);
    }
    void upload_memory() {
        for(unsigned p=0;p<2;p++)for(unsigned y=0;y<256;y++)
            for(unsigned c=0;c<256;c+=2) {
                write((p?0xa0000000u:0xa4000000u)+(y<<14)+(c<<4),
                      fg[p][y*1024+c]|(uint32_t(fg[p][y*1024+c+1])<<16));
                write((p?0xb4000000u:0xb0000000u)+(y<<14)+(c<<4),
                      bg[p][y*1024+c]|(uint32_t(bg[p][y*1024+c+1])<<16));
            }
    }
    void populate(unsigned mode,unsigned page,unsigned phase) {
        oracle.m_screen_control=mode;
        oracle.m_xscroll[0]=7;oracle.m_xscroll[1]=253;
        oracle.m_yscroll[0]=2;oracle.m_yscroll[1]=251;
        for(unsigned p=0;p<2;p++)for(unsigned y=0;y<256;y++) {
            for(unsigned c=0;c<256;c++) {
                fg[p][y*1024+c]=((c+y+p)%9==0)?uint8_t(1+(c*7+y*13+p*31)%255):0;
                bg[p][y*1024+c]=uint16_t(((c*3+y*7+p*53+1)&255)|(((c*11+y*17+p*37+5)&255)<<8));
            }
        }
        upload_memory();
        write(0x20000180,(page<<15)|(mode<<8),12);
        oracle.m_vram_fg_display=fg[1-page].data();
        write(0x20000200,(2<<8)|7,12);write(0x20000280,(251<<8)|253,12);
        write(0x20000300,0,14);
        for(unsigned i=0;i<256;i++) {
            unsigned r=(i>>2)&63,g=i&63,b=(i*7)&63;
            palette.data[i]=((r*4+(r>>4))<<16)|((g*4+(g>>4))<<8)|(b*4+(b>>4));
            for(auto val:{r,g,b})write(0x20000320,val,14);
        }
        // The visible region and clocks are the normal 512x224 raster. Both
        // horizontal parities and boot phases must produce the same byte order.
        heblnk=64+(phase&1);
        io(0, (40<<16)|2);io(0x20,(heblnk<<16)|3);
        io(0x40,((heblnk+512)<<16)|227);io(0x60,(639<<16)|256);
        io(0x200,0);io(0x220,0);io(0x240,0x4000);
        tick((phase>>1)*8);
        io(0x80,0x8000);rendering=true;
    }
    static void load(const std::filesystem::path& file,void* data,size_t size,size_t allocated=0) {
        if(std::filesystem::file_size(file)!=(allocated?allocated:size))throw std::runtime_error("unexpected state file size: "+file.string());
        std::ifstream f(file,std::ios::binary);f.read(static_cast<char*>(data),size);
        if(!f)throw std::runtime_error("state read failed");
    }
    void populate_capture(const std::filesystem::path& folder,unsigned n) {
        std::ostringstream s;s<<"state-"<<std::setfill('0')<<std::setw(4)<<n<<'-';
        std::string prefix=s.str();
        for(unsigned p=0;p<2;p++) {
            // MAME allocates oversized shares. Its address/scanout masks
            // reach only the first 256 KiB of FG and 256K BG words.
            load(folder/(prefix+"vram_fg"+std::to_string(p)+".bin"),fg[p].data(),fg[p].size(),2097152);
            load(folder/(prefix+"vram_bg"+std::to_string(p)+".bin"),bg[p].data(),bg[p].size()*2,4194304);
        }
        uint32_t io_words[32];uint8_t dac[768];
        load(folder/(prefix+"io.bin"),io_words,sizeof(io_words));
        load(folder/(prefix+"palette.bin"),dac,sizeof(dac));
        unsigned display,scroll0,scroll1,mask;
        std::ifstream meta(folder/(prefix+"meta.txt"));meta>>display>>scroll0>>scroll1>>mask;
        if(!meta)throw std::runtime_error("state metadata read failed");
        upload_memory();
        write(0x20000180,display,12);write(0x20000200,scroll0,12);write(0x20000280,scroll1,12);
        oracle.m_screen_control=(display>>8)&3;
        oracle.m_vram_fg_display=fg[(display&0x8000)?0:1].data();
        oracle.m_xscroll[0]=scroll0&255;oracle.m_yscroll[0]=scroll0>>8;
        oracle.m_xscroll[1]=scroll1&255;oracle.m_yscroll[1]=scroll1>>8;
        write(0x20000340,mask,14);write(0x20000300,0,14);
        for(unsigned i=0;i<256;i++) {
            unsigned r=dac[3*i]&63,g=dac[3*i+1]&63,b=dac[3*i+2]&63;
            palette.data[i]=(i&mask)!=i?0:((r*4+(r>>4))<<16)|((g*4+(g>>4))<<8)|(b*4+(b>>4));
            for(auto val:{r,g,b})write(0x20000320,val,14);
        }
        heblnk=io_words[1]>>16;
        if((io_words[2]>>16)-heblnk!=512)throw std::runtime_error("captured horizontal timing is not 512 pixels");
        for(unsigned reg:{0u,1u,2u,3u,16u,17u,18u})io(reg*32,io_words[reg]);
        io(0x80,io_words[4]|0x8000);rendering=true;
        // Replay the writes belonging to the frame just completed by MAME.
        // The post-frame snapshot alone loses its split-screen scroll changes.
        std::ifstream events(folder/"display_events.txt");std::string line;
        unsigned old_scroll0=0,old_scroll1=0;
        while(std::getline(events,line)) {
            unsigned f;DisplayEvent e;
            if(std::sscanf(line.c_str(),"write frame=%u vpos=%u hcount=%u display=%x scroll0=%x scroll1=%x",
                          &f,&e.v,&e.h,&e.display,&e.scroll0,&e.scroll1)==6) {
                e.address=e.scroll0!=old_scroll0?0x20000200:
                          e.scroll1!=old_scroll1?0x20000280:0x20000180;
                if(f==n-1)display_events.push_back(e);
                old_scroll0=e.scroll0;old_scroll1=e.scroll1;
            }
        }
        // frame_done is in vertical blanking (VCOUNT 247), so its journal
        // interval crosses physical line zero. Replay in cyclic raster order.
        std::stable_sort(display_events.begin(),display_events.end(),
            [](const DisplayEvent& a,const DisplayEvent& b){return a.v<b.v || (a.v==b.v && a.h<b.h);});
        previous_vcount=top.VCOUNT;
    }
    void save(const std::string& label) {
        for(unsigned reference=0;reference<2;reference++) {
            const auto& data=reference?captured_expected:captured_actual;
            if(data.size()!=512*224)throw std::runtime_error("captured frame dimensions differ");
            std::ofstream f((reference?"mame-":"native-")+label+".ppm",std::ios::binary);
            f<<"P6\n512 224\n255\n";
            for(uint32_t rgb:data)for(unsigned shift:{16u,8u,0u})f.put(char(rgb>>shift));
        }
    }
};
int main(int argc,char** argv) {
    Verilated::commandArgs(argc,argv);
    uint64_t pixels=0,mismatches=0;
    if(argc>1) {
        for(unsigned n:{350u,600u,900u,1500u,1800u}) {
            Raster r;r.populate_capture(argv[1],n);
            while(r.frame<4 && r.cycles<10000000)r.tick();
            if(r.frame<4)throw std::runtime_error("captured raster did not complete");
            r.save(std::to_string(n));pixels+=r.pixels;mismatches+=r.mismatches;
            std::cout<<"captured MAME frame="<<n<<" pixels="<<r.pixels<<" mismatches="<<r.mismatches<<std::endl;
        }
        std::cout<<"MAME captured raster pixels="<<pixels<<" mismatches="<<mismatches<<'\n';
        return mismatches?1:0;
    }
    for(unsigned mode=0;mode<4;mode++)for(unsigned phase=0;phase<4;phase++) {
        Raster r;r.populate(mode,mode&1,phase);
        while(r.frame<4 && r.cycles<10000000)r.tick();
        if(r.frame<4 || r.pixels<512*224)throw std::runtime_error("no complete video frame");
        pixels+=r.pixels;mismatches+=r.mismatches;
    }
    {
        Raster r;r.populate(2,0,0);bool wrote=false;
        while(r.frame<4 && r.cycles<10000000) {
            r.tick();
            if(!wrote && r.frame==2 && r.top.VCOUNT==13 && r.x==80) {
                // MAME renders the complete line with the state at its start.
                // A CPU write to a later pixel must appear on a future refresh.
                r.write(0xb4000000u+(5u<<14)+(96u<<4),0xfefffffeu);
                r.bg[1][5*1024+96]=0xfffe;r.bg[1][5*1024+97]=0xfeff;
                wrote=true;
            }
        }
        if(!wrote || r.frame<4)throw std::runtime_error("active-line BG write was not exercised");
        pixels+=r.pixels;mismatches+=r.mismatches;
    }
    std::cout<<"MAME raster pixels="<<pixels<<" mismatches="<<mismatches<<" modes=4 pages=2 horizontal_phases=2 boot_phases=2\n";
    return mismatches?1:0;
}
