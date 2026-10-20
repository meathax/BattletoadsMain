#include "VBT_GRAPHICS_SIM.h"
#include "verilated.h"
#include "mame_row.h"
#include <array>
#include <cstdint>
#include <cstdio>
#include <stdexcept>
#include <string>
#include <vector>
#include "gameplay_configurations.h"
#include "gameplay_source.h"

struct Bench {
    VerilatedContext context;
    VBT_GRAPHICS_SIM dut{&context};
    uint64_t cycles=0;
    uint64_t mem_cycles=0;
    std::array<uint16_t,512> source{};
    std::array<uint16_t,512> written_source{};
    std::vector<uint32_t> foreground_upper = std::vector<uint32_t>(1u<<18,0);
    bool upper_request=false;
    unsigned upper_wait=0;
    unsigned upper_transactions=0;
    uint32_t upper_reply=0;
    Bench() {
        dut.RST_N=0; dut.BUS_RAS_N=1; dut.BUS_WE_N=1;
        dut.BUS_QE_N=1; dut.BUS_CAS_N=15; dut.ERDY=1;
        uint32_t seed=0x42f01937u;
        for(unsigned i=0;i<512;i++) {
            seed^=seed<<13; seed^=seed>>17; seed^=seed<<5;
            source[i]=has_captured_source?captured_source[i]:uint16_t(seed^(seed>>16));
        }
        tick(4); dut.RST_N=1; tick(4);
    }
    void tick(unsigned n=1) {
        for(unsigned t=0;t<n;t++) {
            dut.CE_R=(cycles&1)==0; dut.CE_F=(cycles&1)!=0;
            for(unsigned phase=0;phase<4;phase++) {
                dut.ESTE=0;
                if(phase&1) {
                    bool request=dut.EFG && (dut.ERD || dut.EWE);
                    if(!request) upper_request=false;
                    if(request && dut.CE_R && !upper_request) {
                        if(upper_wait) throw std::runtime_error("overlapping foreground DDR requests");
                        unsigned address=dut.EADDR>>2;
                        if(address>=foreground_upper.size()) throw std::runtime_error("foreground upper address");
                        auto& word=foreground_upper[address];
                        for(unsigned lane=0;lane<4;lane++)
                            if(dut.EWE&(1u<<lane)) word=(word&~(255u<<(8*lane))) |
                                (dut.EDATA&(255u<<(8*lane)));
                        upper_reply=word;
                        upper_wait=(upper_transactions++%3)==0 ? 0 : 13;
                        upper_request=true;
                    }
                    dut.ERDY=upper_wait==0;
                    if(upper_wait) upper_wait--;
                    else dut.EQ=upper_reply;
                    if(!dut.ESRD && !dut.ESWR) beats=0;
                    else if((mem_cycles%3)==0) {
                        unsigned p=beats*4;
                        if(dut.ESRD) {
                            dut.ESQ=uint64_t(source[p] | (uint32_t(source[p+1])<<16))<<32;
                            dut.ESQ|=source[p+2] | (uint32_t(source[p+3])<<16);
                        } else {
                            written_source[p]=dut.ESDATA>>32;
                            written_source[p+1]=dut.ESDATA>>48;
                            written_source[p+2]=dut.ESDATA;
                            written_source[p+3]=dut.ESDATA>>16;
                        }
                        dut.ESTE=1;
                    }
                }
                dut.CLK=(phase>>1); dut.CLK2X=(phase&1);
                dut.eval(); context.timeInc(1);
                if(phase&1) {
                    mem_cycles++;
                    if(dut.ESTE) beats=(beats+1)&127;
                }
            }
            cycles++;
        }
    }
    unsigned beats=0;
    unsigned refresh_wait_errors=0;
    void idle(unsigned n=4) {
        dut.BUS_RAS_N=1; dut.BUS_WE_N=1; dut.BUS_QE_N=1;
        dut.BUS_CAS_N=15; tick(n);
    }
    uint32_t bus(uint32_t a,uint32_t d,bool we,bool qe,uint8_t cas=0,
                 uint8_t code=8) {
        idle(); dut.BUS_BIT_ADDR=a; dut.BUS_ADDR=(a&~15u)|code; dut.BUS_DATA=d;
        dut.BUS_RAS_N=0; dut.BUS_WE_N=!we; dut.BUS_QE_N=!qe;
        dut.BUS_CAS_N=cas; tick(4);
        unsigned watchdog=0;
        while(!dut.BUS_READY) {
            tick(); if(++watchdog>1000000) throw std::runtime_error("bus timeout");
        }
        tick(2); uint32_t q=dut.BUS_Q;
        if(code==4 && !dut.SCAN_READY) refresh_wait_errors++;
        idle(); return q;
    }
    void reg(unsigned offset,uint16_t data,uint8_t cas=12) {
        bus(0x20000000u+offset,data,true,false,cas);
    }
    void load_source(unsigned offset,bool mirror=false) {
        bus((mirror?0xe8000000u:0xa8000000u)+(offset<<3),0,false,true,0,5);
    }
    void set_destination(unsigned row,unsigned x,bool mirror=false) {
        bus((mirror?0xe4000000u:0xa4000000u)+(row<<14)+(x<<5),0,false,true,0,5);
    }
    void draw(uint32_t address=0xac000000u) { bus(address,0,true,true,0,5); tick(5000); }
    void seed(unsigned row,const std::array<uint8_t,512>& data) {
        for(unsigned x=0;x<512;x+=2)
            bus(0xa4000000u+(row<<14)+(x<<4),
                data[x] | (uint32_t(data[x+1])<<16),true,false);
    }
    uint8_t pixel(unsigned row,unsigned x) {
        uint32_t v=bus(0xa4000000u+(row<<14)+(x<<4),0,false,true);
        return (v >> ((x&1)*16))&255;
    }
};

int main(int argc,char** argv) {
    const bool baseline=argc>1 && std::string(argv[1])=="--baseline";
    try {
        Bench b;
        unsigned tests=0, bad=0, errors_printed=0;
        auto run=[&](unsigned width,unsigned src,unsigned dst,
                     unsigned ss,unsigned ds,bool flip,bool shadow,bool page,unsigned bank=11) {
            MameRow ref;
            std::array<uint8_t,512> expected;
            for(unsigned x=0;x<512;x++) expected[x]=uint8_t(0x80|(x%127));
            ref.m_sprite_dest_base=expected.data();
            ref.control=((bank<<12) | ((~(width-2))&511u) | (flip?1024u:0));
            ref.scale[0]=ss; ref.scale[4]=ds;
            ref.m_sprite_source_offs=src; ref.m_sprite_dest_offs=dst;
            ref.m_misc_control=shadow?16:0;
            b.reg(0x180,page?0x8000:0);
            b.seed(3,expected);
            b.load_source(src); b.set_destination(3,dst);
            b.reg(0,ss); b.reg(0x80,ds); b.reg(0x100,ref.control);
            b.reg(0x400,shadow?16:0);
            for(unsigned row=0;row<3;row++) {
                ref.render_sprite_row(b.source.data(),0xac000000);
                b.draw();
                for(unsigned x=0;x<512;x++) {
                    auto actual=b.pixel(3,x);
                    if(actual!=expected[x]) {
                        bad++;
                        if(errors_printed++<6)
                            std::printf("DIFF width=%u src=%u dst=%u scales=%u,%u flip=%d shadow=%d page=%d row=%u x=%u actual=%02x expected=%02x\n",
                                width,src,dst,ss,ds,flip,shadow,page,row,x,actual,expected[x]);
                    }
                }
            }
            tests++;
        };
        if(baseline) run(17,4,19,0,0,false,false,false);
        else {
            for(unsigned width=2;width<=513;width++)
                run(width,width%2048,(width*7)%512,0,0,width&1,width&2,width&4);
            const unsigned widths[]={2,3,17,255,256,511,513};
            const unsigned scales[]={0,1,63,127,128,192,255};
            for(unsigned width:widths)
                for(unsigned scale:scales)
                    for(unsigned dest_scale:scales)
                        run(width,2045,509,scale,dest_scale,true,true,true);
            run(17,3,19,128,256,false,false,false);
            // Reverse destination steps are legal; source steps must be positive
            // for the MAME loop to terminate.
            run(17,1,1,127,384,false,false,false);
            for(unsigned bank=0;bank<16;bank++) for(unsigned flags=0;flags<4;flags++)
                run(17,3,509,128,63,flags&1,flags&2,bank&1,bank);
            unsigned command=0;
            for(const auto& cfg:gameplay_configurations) {
                run((~cfg[2]&511)+2,(command++*37)&2047,509,cfg[0],cfg[1],
                    cfg[2]&1024,cfg[3]!=0,cfg[4]&32768,cfg[2]>>12);
            }
        }
        unsigned priority_cases=0,scroll_cases=0,scan_pixels=0,palette_checks=0,shift_checks=0,register_checks=0,background_read_checks=0,destination_page_checks=0,foreground_upper_checks=0;
        unsigned foreground_unaligned_checks=0;
        unsigned cursor_wrap_rows=0;
        if(!baseline) {
            MameRow ref;
            std::array<uint8_t,512> expected{};
            ref.m_sprite_dest_base=expected.data();
            ref.control=0x5400; // 513 source pixels, flipped nibbles
            ref.scale[0]=29; ref.scale[4]=511;
            ref.m_sprite_source_offs=2047; ref.m_sprite_dest_offs=17;
            ref.m_misc_control=0;
            b.reg(0x180,0); b.seed(82,expected);
            b.load_source(2047); b.set_destination(82,17);
            b.reg(0,29); b.reg(0x80,511); b.reg(0x100,ref.control); b.reg(0x400,0);
            for(unsigned row=0;row<300;row++) {
                ref.render_sprite_row(b.source.data(),0xac000000u);
                b.draw();
                for(unsigned x=0;x<512;x++) {
                    if(b.pixel(82,x)!=expected[x]) {
                        bad++;
                        if(errors_printed++<8) std::printf("CURSOR WRAP DIFF row=%u x=%u\n",row,x);
                    }
                }
                cursor_wrap_rows++;
            }
        }
        unsigned graphics_mapping_checks=0;
        unsigned foreground_video_copy_checks=0;
        for(unsigned page=0;page<2;page++) {
            b.dut.VCE_R=0;
            b.reg(0x180,page<<15);
            std::array<uint8_t,512> video{},cpu{};
            for(unsigned x=0;x<512;x++) { video[x]=1+(x%63); cpu[x]=0x50+(x%16); }
            b.seed(67,video); b.seed(68,cpu);
            b.reg(0x180,(page^1)<<15);
            for(unsigned offset : {0u,1u,7u,511u,512u,767u,1023u}) {
                b.bus(0xa0000000u+(67<<14),0,false,true,0,4);
                b.bus(0xa0000000u+(68<<14)+(offset<<4),0,false,true,0,5);
                if(b.dut.PIXEL!=video[0]) {
                    bad++;
                    if(errors_printed++<8) std::printf("FG VIDEO READ DIFF page=%u offset=%u actual=%02x\n",page,offset,b.dut.PIXEL);
                }
                foreground_video_copy_checks++;
            }
            b.load_source(0);
            b.bus(0xa0000000u+(67<<14),0,false,true,0,4);
            b.tick(2);
            std::array<uint8_t,32> scan{};
            b.dut.VCE_R=1;
            for(auto& value:scan) { b.tick(); value=b.dut.PIXEL; }
            b.dut.VCE_R=0; b.tick(3);
            b.bus(0xa0000000u+(67<<14),0,false,true,0,4);
            b.bus(0xa0000000u+(68<<14),0,true,true,0,5);
            b.tick(2); b.dut.VCE_R=1;
            for(unsigned x=0;x<scan.size();x++) {
                b.tick();
                if(b.dut.PIXEL!=scan[x]) {
                    bad++;
                    if(errors_printed++<8) std::printf("FG VIDEO WRITE DIFF page=%u pixel=%u\n",page,x);
                }
                foreground_video_copy_checks++;
            }
            b.dut.VCE_R=0; b.tick(3);
        }
        for(unsigned page=0;page<2;page++) {
            b.reg(0x180,page<<15);
            std::array<uint8_t,512> pixels{};
            for(unsigned x=0;x<512;x++) pixels[x]=1+(x%255);
            b.seed(61,pixels);
            for(unsigned display=0;display<2;display++) {
                b.reg(0x180,(page^display)<<15);
                uint32_t base=display?0xa0000000u:0xa4000000u;
                unsigned cell=(61<<14)+(18<<4);
                uint32_t expected=pixels[18] | (uint32_t(pixels[19])<<16);
                for(uint32_t extra : {0x00400000u,0x00800000u,0x00c00000u,0x40000000u}) {
                    b.bus(base+extra+cell,0,true,false);
                    if(b.bus(base+cell,0,false,true)!=expected) bad++;
                    if(b.bus(base+extra+cell,0,false,true)!=0xffffffffu) bad++;
                    graphics_mapping_checks+=2;
                }
            }
        }
        for(uint32_t address : {0xa8800000u,0xa9000000u,0xab000000u,0xe8000000u}) {
            if(b.bus(address,0,false,true)!=0xffffffffu) bad++;
            graphics_mapping_checks++;
        }
        // MAME memcpy starts at the complete logical address, including column.
        for(unsigned page=0;page<2;page++) {
            b.reg(0x180,page<<15);
            std::array<uint8_t,2048> logical{};
            for(unsigned i=0;i<logical.size();i++) logical[i]=1+((i*29+page*71+(i>>3))%255);
            for(unsigned row=0;row<2;row++) {
                std::array<uint8_t,512> low{};
                for(unsigned x=0;x<512;x++) low[x]=logical[row*1024+x];
                b.seed(53+row,low);
                for(unsigned x=512;x<1024;x+=2)
                    b.bus(0xa4000000u+((53+row)<<14)+(x<<4),
                        logical[row*1024+x] | (uint32_t(logical[row*1024+x+1])<<16),true,false);
            }
            b.reg(0x180,(page^1)<<15);
            for(unsigned offset : {1u,7u,15u,255u,511u,512u,513u,767u,1023u}) {
                b.load_source(0);
                b.bus(0xa0000000u+(53<<14)+(offset<<4),0,false,true,0,5);
                b.bus(0xa8000000u,0,true,true,0,5);
                for(unsigned i=0;i<1024;i++) {
                    unsigned expected=i<512 ? logical[offset+i] :
                        ((b.source[i>>1]>>((i&1)*8))&255);
                    unsigned actual=(b.written_source[i>>1]>>((i&1)*8))&255;
                    if(actual!=expected) {
                        bad++;
                        if(errors_printed++<8) std::printf("FG UNALIGNED DIFF page=%u offset=%u byte=%u\n",page,offset,i);
                    }
                    foreground_unaligned_checks++;
                }
            }
        }
        // MAME keeps the upper 512 bytes independent from each displayed row.
        // The game clears these addresses during play; they must not erase sprites.
        for(unsigned page=0;page<2;page++) {
            b.reg(0x180,page<<15);
            std::array<uint8_t,512> pixels{};
            for(unsigned x=0;x<512;x++) pixels[x]=1+((x*73+page*41)%255);
            b.seed(41,pixels);
            for(unsigned x=0;x<512;x+=2)
                b.bus(0xa4000000u+(41<<14)+0x2000+(x<<4),0,true,false);
            for(unsigned x=0;x<512;x++) {
                if(b.pixel(41,x)!=pixels[x]) {
                    bad++;
                    if(errors_printed++<8) std::printf("FG UPPER CLEAR DIFF page=%u x=%u\n",page,x);
                }
                foreground_upper_checks++;
            }
            for(unsigned x=0;x<512;x+=2) {
                unsigned address=0xa4000000u+(41<<14)+0x2000+(x<<4);
                uint32_t expected=pixels[x] | (uint32_t(pixels[x+1])<<16);
                b.bus(address,expected|0xab00cd00u,true,false);
                b.bus(address,0xffffffffu,true,false,5);
                if(b.bus(address,0,false,true)!=expected) bad++;
                foreground_upper_checks++;
            }
            b.reg(0x180,(page^1)<<15);
            for(unsigned x=0;x<512;x+=2) {
                uint32_t expected=pixels[x] | (uint32_t(pixels[x+1])<<16);
                if(b.bus(0xa0000000u+(41<<14)+0x2000+(x<<4),0,false,true)!=expected) bad++;
                foreground_upper_checks++;
            }
        }
        if(!baseline) {
            for(unsigned page=0;page<2;page++) {
                std::array<uint8_t,512> expected, untouched;
                expected.fill(0xa5); untouched.fill(0x5b);
                b.reg(0x180,page?0x8000:0); b.seed(17,expected);
                b.reg(0x180,page?0:0x8000); b.seed(17,untouched);
                b.reg(0x180,page?0x8000:0);
                b.load_source(3,true); b.set_destination(17,509,true);
                // A page flip after destination setup cannot change the saved
                // MAME destination pointer, including when AC uses a mirror.
                b.reg(0x180,page?0:0x8000);
                MameRow ref;
                ref.m_sprite_dest_base=expected.data();
                ref.control=0xb400|((~15u)&511); ref.scale[0]=128; ref.scale[4]=192;
                ref.m_sprite_source_offs=3; ref.m_sprite_dest_offs=509;
                b.reg(0,128); b.reg(0x80,192); b.reg(0x100,ref.control); b.reg(0x400,0);
                ref.render_sprite_row(b.source.data(),0xec00caa0);
                b.draw(0xec00caa0);
                for(unsigned x=0;x<512;x++) {
                    auto actual=b.bus(0xa0000000u+(17u<<14)+(x<<4),0,false,true);
                    if(((actual>>((x&1)*16))&255)!=expected[x] || b.pixel(17,x)!=untouched[x]) {
                        bad++;
                        if(errors_printed++<10) std::printf("DESTINATION PAGE DIFF saved_page=%u x=%u\n",page,x);
                    }
                    destination_page_checks+=2;
                }
            }
        }
        if(!baseline) {
            auto expect_shift=[&](unsigned actual,unsigned expected,const char* what,unsigned x) {
                shift_checks++;
                if(actual!=expected) {
                    bad++;
                    if(errors_printed++<10) std::printf("SHIFT DIFF %s x=%u actual=%04x expected=%04x\n",what,x,actual,expected);
                }
            };
            std::array<uint8_t,512> row;
            for(unsigned page=0;page<2;page++) {
                // A8 -> A0 copies the first 512 bytes of the shared TMS register.
                b.load_source(0); b.reg(0x180,page?0:0x8000);
                b.bus(0xa0000000u+(7u<<14),0,true,true,0,5);
                for(unsigned x=0;x<512;x++) {
                    unsigned expected=(b.source[x/2]>>((x&1)*8))&255;
                    auto actual=b.bus(0xa0000000u+(7u<<14)+(x<<4),0,false,true);
                    expect_shift((actual>>((x&1)*16))&255,expected,"sprite to foreground",x);
                    row[x]=uint8_t((x*37+page*83)&255);
                }
                // A0 -> A8 replaces only the first half of the 1024-byte register.
                b.reg(0x180,page?0x8000:0); b.seed(9,row);
                b.reg(0x180,page?0:0x8000);
                b.bus(0xa0000000u+(9u<<14),0,false,true,0,5);
                b.bus(0xa8000000u,0,true,true,0,5);
                for(unsigned x=0;x<512;x++) {
                    unsigned expected=x<256?row[x*2]|(unsigned(row[x*2+1])<<8):b.source[x];
                    expect_shift(b.written_source[x],expected,"foreground to sprite",x);
                }
                // The same register survives a page change before A0 writeback.
                b.reg(0x180,page?0x8000:0);
                b.bus(0xe0000000u+(10u<<14),0,true,true,0,5);
                for(unsigned x=0;x<512;x++) {
                    auto actual=b.bus(0xa0000000u+(10u<<14)+(x<<4),0,false,true);
                    expect_shift((actual>>((x&1)*16))&255,row[x],"foreground page copy and mirror",x);
                }
            }
        }
        if(!baseline) {
            const unsigned colors[]={0,1,127,128,129,255};
            for(unsigned mode=0;mode<4;mode++) for(unsigned s:colors)
                for(unsigned g0:colors) for(unsigned g1:colors) {
                    unsigned expected=0;
                    switch(mode) {
                    case 0: expected=s && !(s&128)?s:g1&128?g1:s?s:g1?g1:g0; break;
                    case 1: expected=s && !(s&128)?s:g0?g0:g1&128?g1:s?s:g1; break;
                    case 2: expected=s?s:g1?g1:g0; break;
                    case 3: expected=g1&128?g1:s&128?s:g1?g1:s?s:g0; break;
                    }
                    b.dut.TEST_MODE=mode; b.dut.TEST_SPR=s;
                    b.dut.TEST_BG0=g0; b.dut.TEST_BG1=g1; b.tick(2);
                    if(b.dut.TEST_PIXEL!=expected) bad++;
                    priority_cases++;
                }
            for(unsigned row:{0u,1u,255u}) {
                for(unsigned col=0;col<256;col+=2) {
                    uint32_t data=uint16_t(col | ((col^0x5a)<<8));
                    data|=uint32_t(uint16_t((col+1) | (((col+1)^0x5a)<<8)))<<16;
                    b.bus(0xb0000000u+(row<<14)+(col<<4),data,true,false);
                    b.bus(0xb4000000u+(row<<14)+(col<<4),data^0xffffffffu,true,false);
                }
                for(unsigned x:{0u,1u,2u,63u,127u,128u,255u}) {
                    b.reg(0x200,(row<<8)|x); b.reg(0x280,(row<<8)|x);
                    b.bus(0,0,false,true,0,4);
                    unsigned expected=x | ((x^0x5a)<<8);
                    if(b.dut.BG0_PAIR!=expected || b.dut.BG1_PAIR!=(expected^65535)) {
                        bad++; std::printf("SCROLL DIFF row=%u x=%u bg0=%04x bg1=%04x expected=%04x\n",
                            row,x,b.dut.BG0_PAIR,b.dut.BG1_PAIR,expected);
                    }
                    scroll_cases++;
                    // Ordinary CPU reads must not redirect the video serial port.
                    b.bus(0xb0000000u+((row^255u)<<14)+(42u<<4),0,false,true);
                    b.bus(0xb4000000u+((row^255u)<<14)+(42u<<4),0,false,true);
                    background_read_checks+=2;
                    if(b.dut.BG0_PAIR!=expected || b.dut.BG1_PAIR!=(expected^65535)) {
                        bad++;
                        if(errors_printed++<10) std::printf("BG READ DIFF row=%u scroll=%u bg0=%04x bg1=%04x expected=%04x\n",row,x,b.dut.BG0_PAIR,b.dut.BG1_PAIR,expected);
                    }
                }
            }
            std::array<uint8_t,512> foreground;
            for(unsigned x=0;x<512;x++) foreground[x]=(x%127)+1;
            b.reg(0x180,0); b.seed(0,foreground);
            b.reg(0x180,0x8200); b.reg(0x200,0); b.reg(0x280,0);
            b.bus(0,0,false,true,0,4);
            b.bus(0xa0000000u+(255u<<14),0,false,true);
            for(unsigned x=0;x<512;x++) {
                if(b.dut.PIXEL!=foreground[x/2]) {
                    bad++;
                    if(x<6) std::printf("SCAN DIFF x=%u actual=%02x expected=%02x\n",x,b.dut.PIXEL,foreground[x/2]);
                }
                b.dut.VCE_R=1; b.tick(); b.dut.VCE_R=0; b.tick(6);
                scan_pixels++;
            }
            foreground.fill(0);
            // MAME has no background from_shiftreg handler: a shift write is
            // ignored and must not become an ordinary bitmap-memory write.
            auto bg_before=b.bus(0xb0000000u,0,false,true);
            b.bus(0xb0000000u,0xdeadbeefu,true,true,0,5);
            if(b.bus(0xb0000000u,0,false,true)!=bg_before) bad++;
            background_read_checks++;
            b.reg(0x180,0); b.seed(0,foreground); b.reg(0x180,0x8200);
            b.bus(0,0,false,true,0,4);
            for(unsigned x=0;x<512;x++) {
                unsigned col=x/2;
                unsigned expected=((x&1)?(col^0x5a):col)^255;
                if(!expected) expected=255;
                if(b.dut.PIXEL!=expected) {
                    bad++;
                    if(x<6) std::printf("BG SCAN DIFF x=%u actual=%02x expected=%02x\n",x,b.dut.PIXEL,expected);
                }
                b.dut.VCE_R=1; b.tick(); b.dut.VCE_R=0; b.tick(6);
                scan_pixels++;
            }
        }
        if(!baseline) {
            auto expect_palette=[&](uint32_t actual,uint32_t expected,const char* what) {
                palette_checks++;
                if(actual!=expected) {
                    bad++;
                    if(errors_printed++<10) std::printf("PALETTE DIFF %s actual=%06x expected=%06x\n",what,actual,expected);
                }
            };
            auto read_reg=[&](unsigned offset) {
                return b.bus(0x20000000u+offset,0,false,true)&255u;
            };
            std::array<uint32_t,256> palette;
            b.reg(0x300,255);
            for(unsigned n=0;n<256;n++) {
                unsigned i=(n+255)&255;
                unsigned r=(i*29+7)&255,g=(i*11+137)&255,blue=(i*43+19)&255;
                palette[i]=(r<<16)|(g<<8)|blue;
                b.reg(0x320,r); b.reg(0x320,g); b.reg(0x320,blue);
            }
            expect_palette(read_reg(0x300),255,"write-address wrap");
            b.reg(0x360,255);
            for(unsigned n=0;n<256;n++) {
                unsigned i=(n+255)&255;
                for(unsigned shift:{16u,8u,0u})
                    expect_palette(read_reg(0x320),(palette[i]>>shift)&255,"raw RGB readback");
            }
            expect_palette(read_reg(0x360),255,"read-address wrap");
            b.reg(0x340,0x12,13); // Byte lane 0 is inactive.
            expect_palette(read_reg(0x340),255,"inactive byte lane");
            std::array<uint8_t,512> foreground;
            for(unsigned x=0;x<512;x++) foreground[x]=x&255;
            b.reg(0x180,0); b.seed(2,foreground);
            b.reg(0x200,0); b.reg(0x280,0); b.reg(0x180,0x8200);
            auto expand=[](unsigned raw) { raw&=63; return (raw<<2)|(raw>>4); };
            for(unsigned mask:{0u,127u,85u,255u}) {
                b.reg(0x340,mask); expect_palette(read_reg(0x340),mask,"pixel mask readback");
                b.bus(2u<<14,0,false,true,0,4);
                for(unsigned x=0;x<512;x++) {
                    unsigned i=x/2;
                    unsigned expected=(i&mask)!=i?0:
                        (expand(palette[i]>>16)<<16)|(expand(palette[i]>>8)<<8)|expand(palette[i]);
                    expect_palette(b.dut.RGB,expected,"six-bit DAC and masked pen");
                    b.dut.VCE_R=1; b.tick(); b.dut.VCE_R=0; b.tick(6);
                }
            }
        }
        if(!baseline) {
            const unsigned offsets[]={0,0x80,0x100,0x180,0x200,0x280,0x400};
            auto state_reg=[&](unsigned index) {
                return (b.dut.REG_STATE[index/2]>>((index&1)*16))&65535u;
            };
            auto expect_reg=[&](unsigned index,unsigned expected) {
                register_checks++;
                unsigned actual=state_reg(index);
                if(actual!=expected) {
                    bad++;
                    if(errors_printed++<10) std::printf("REGISTER DIFF offset=%03x actual=%04x expected=%04x\n",offsets[index],actual,expected);
                }
            };
            for(unsigned i=0;i<7;i++) {
                b.reg(offsets[i],0xa65b); expect_reg(i,i==3?0xa600:0xa65b);
                b.reg(offsets[i],0xff18,14); expect_reg(i,i==3?0xa600:0xa618);
                b.reg(offsets[i],0x2c00,13); expect_reg(i,i==3?0x2c00:0x2c18);
                b.reg(offsets[i],0xffff,15); expect_reg(i,i==3?0x2c00:0x2c18);
            }
        }
        bad+=b.refresh_wait_errors;
        std::printf("sprite_cases=%u rows=%u cursor_wrap_rows=%u priority_cases=%u scroll_cases=%u scan_pixels=%u palette_checks=%u shift_checks=%u register_checks=%u background_read_checks=%u destination_page_checks=%u foreground_upper_checks=%u foreground_unaligned_checks=%u graphics_mapping_checks=%u foreground_video_copy_checks=%u refresh_wait_errors=%u mismatches=%u\n",tests+(cursor_wrap_rows?1:0),tests*3+cursor_wrap_rows,cursor_wrap_rows,priority_cases,scroll_cases,scan_pixels,palette_checks,shift_checks,register_checks,background_read_checks,destination_page_checks,foreground_upper_checks,foreground_unaligned_checks,graphics_mapping_checks,foreground_video_copy_checks,b.refresh_wait_errors,bad);
        b.dut.final();
        return bad?1:0;
    } catch(const std::exception& e) { std::fprintf(stderr,"%s\n",e.what()); return 2; }
}
