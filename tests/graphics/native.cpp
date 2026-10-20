#include "VBT_NATIVE_SIM.h"
#include "verilated.h"
#include <cstdint>
#include <fstream>
#include <iostream>
#include <vector>
#include <string>
#include <stdexcept>
#include <filesystem>
#include <chrono>
#include <cstdio>

static std::vector<uint8_t> read_file(const char* name) {
    std::ifstream f(name,std::ios::binary);
    if(!f) throw std::runtime_error(std::string("missing file: ")+name);
    return {std::istreambuf_iterator<char>(f),{}};
}
int main(int argc,char** argv) {
    if(argc!=6 && argc!=7) {std::cerr<<"main.bin audio.bin samples.bin output frames [MAME input journal]\n";return 2;}
    std::vector<uint8_t> input_journal;
    if(argc==7) {
        std::ifstream input(argv[6]);std::string line;
        if(!input) throw std::runtime_error("missing MAME input journal");
        input_journal.resize(std::stoi(argv[5])+1,0xff);
        unsigned expected=1;
        while(std::getline(input,line)) {
            unsigned index,value;
            if(std::sscanf(line.c_str(),"frame=%u p1=%x",&index,&value)!=2 || index!=expected++)
                throw std::runtime_error("invalid MAME input journal sequence");
            if(index<input_journal.size()) input_journal[index]=value&0xff;
        }
        if(expected<=unsigned(std::stoi(argv[5]))) throw std::runtime_error("short MAME input journal");
    }
    auto rom=read_file(argv[1]),audio=read_file(argv[2]),samples=read_file(argv[3]);
    if(rom.size()!=0x800000 || audio.size()!=0x8000 || samples.size()!=0x200000) return 3;
    std::filesystem::create_directories(argv[4]);
    VerilatedContext ctx;ctx.commandArgs(argc,argv);
    VBT_NATIVE_SIM top(&ctx);
    std::vector<uint64_t> memory(0x2400000/8,0);
    for(size_t i=0;i<rom.size();i+=8) {
        uint64_t q=0;
        for(int j=0;j<4;j++) {q|=uint64_t(rom[i+j])<<(32+j*8);q|=uint64_t(rom[i+4+j])<<(j*8);}
        memory[i/8]=q;
    }
    uint64_t mem_clock=0,sys_clock=0,read_address=0;unsigned read_count=0,read_wait=0;
    uint64_t commands=0,reads=0,writes=0,cpu_reads=0,cpu_writes=0;
    int frame=0,x=0,y=0,width=0;bool old_h=true,old_v=true;
    std::vector<uint8_t> pixels;
    int pre_frame=0,pre_x=0,pre_y=0,pre_width=0;bool pre_old_h=true,pre_old_v=true;
    std::vector<uint8_t> pre_pixels;
    std::ofstream trace(std::string(argv[4])+"/trace.csv");
    trace<<"frame,sys_clock,pc,instruction,state,display,width,height,cpu_reads,cpu_writes,ddr_reads,ddr_writes\n";
    top.RESET=1;top.P1=0xff;
    auto memory_edge=[&]() {
        bool busy=(mem_clock%17)<3;
        top.DDR_BUSY=busy;top.DDR_Q_READY=0;
        if(read_count) {
            if(read_wait) --read_wait;
            else if(mem_clock%3!=0) {
                if(read_address>=memory.size()) throw std::runtime_error("DDR read outside model");
                top.DDR_Q=memory[read_address++];top.DDR_Q_READY=1;--read_count;
            }
        }
        if(!busy && top.DDR_WE) {
            size_t a=top.DDR_ADDR & 0x1ffffff;
            if(a>=memory.size()) throw std::runtime_error("DDR write outside model");
            for(int j=0;j<8;j++) if((top.DDR_BE>>j)&1)
                memory[a]=(memory[a]&~(uint64_t(0xff)<<(j*8))) | (top.DDR_DATA&(uint64_t(0xff)<<(j*8)));
            ++writes;++commands;
        }
        if(!busy && top.DDR_RD) {
            if(read_count) throw std::runtime_error("overlapping DDR burst");
            read_address=top.DDR_ADDR & 0x1ffffff;
            read_count=top.DDR_BURST;read_wait=6;++reads;++commands;
        }
        ++mem_clock;
    };
    auto tick=[&]() {
        top.CLK=0;top.CLK2X=0;top.eval();ctx.timeInc(3);
        top.SAMPLE_DATA=samples[top.SAMPLE_ADDR & 0x1fffff];
        memory_edge();
        bool pixel=top.PIXEL_CE;
        // MiSTer's video_mixer samples RGB and blanking together before the
        // clock edge. Retain that raster beside the post-edge diagnostic.
        bool pre_h=top.HBL_N,pre_v=top.VBL_N;
        uint32_t pre_rgb=top.RGB;
        bool read=top.CPU_CE&&top.BUS_READ,write=top.CPU_CE&&top.BUS_WRITE;
        top.CLK=1;top.CLK2X=1;top.eval();ctx.timeInc(3);
        if(read)cpu_reads++;if(write)cpu_writes++;
        if(pixel && !top.RESET && top.INIT_READY) {
            if(!old_v && top.VBL_N) {pixels.clear();x=y=width=0;}
            if(top.VBL_N) {
                if(!old_h && top.HBL_N) x=0;
                if(top.HBL_N) {
                    pixels.push_back(top.RGB>>16);pixels.push_back(top.RGB>>8);pixels.push_back(top.RGB);++x;
                }
                if(old_h && !top.HBL_N && x) {width=x;++y;}
            }
            if(old_v && !top.VBL_N && y) {
                ++frame;
                trace<<frame<<','<<sys_clock<<','<<std::hex<<top.PC<<','<<top.INSTRUCTION
                    <<','<<unsigned(top.MICRO_STATE)<<','<<top.DISPLAY_CONTROL<<std::dec
                    <<','<<width<<','<<y<<','<<cpu_reads<<','<<cpu_writes<<','<<reads<<','<<writes<<'\n';
                trace.flush();
                if(frame<=10 || frame%50==0 || frame==350 || frame==600 || frame==900 || frame==1500 || frame==1800) {
                    if(pixels.size()!=size_t(width*y*3)) throw std::runtime_error("variable active scanline width");
                    std::ofstream f(std::string(argv[4])+"/frame-"+std::to_string(frame)+".ppm",std::ios::binary);
                    f<<"P6\n"<<width<<' '<<y<<"\n255\n";
                    f.write(reinterpret_cast<const char*>(pixels.data()),pixels.size());
                    std::cout<<"frame="<<frame<<" pc="<<std::hex<<top.PC<<" display="<<top.DISPLAY_CONTROL<<std::dec
                        <<" raster="<<width<<'x'<<y<<" sys_cycles="<<sys_clock<<std::endl;
                }
                top.P1=input_journal.empty()?0xff:input_journal[frame];
            }
            old_h=top.HBL_N;old_v=top.VBL_N;
            if(!pre_old_v && pre_v) {pre_pixels.clear();pre_x=pre_y=pre_width=0;}
            if(pre_v) {
                if(!pre_old_h && pre_h)pre_x=0;
                if(pre_h) {
                    pre_pixels.push_back(pre_rgb>>16);pre_pixels.push_back(pre_rgb>>8);
                    pre_pixels.push_back(pre_rgb);++pre_x;
                }
                if(pre_old_h && !pre_h && pre_x) {pre_width=pre_x;++pre_y;}
            }
            if(pre_old_v && !pre_v && pre_y) {
                ++pre_frame;
                if(pre_frame<=10 || pre_frame%50==0) {
                    if(pre_pixels.size()!=size_t(pre_width*pre_y*3))throw std::runtime_error("variable pre-edge raster width");
                    auto folder=std::filesystem::path(argv[4]).parent_path()/"frames-pre";
                    std::filesystem::create_directories(folder);
                    std::ofstream f(folder/("frame-"+std::to_string(pre_frame)+".ppm"),std::ios::binary);
                    f<<"P6\n"<<pre_width<<' '<<pre_y<<"\n255\n";
                    f.write(reinterpret_cast<const char*>(pre_pixels.data()),pre_pixels.size());
                }
            }
            pre_old_h=pre_h;pre_old_v=pre_v;
        }
        top.CLK2X=0;top.eval();ctx.timeInc(3);
        top.CLK=0;memory_edge();top.CLK2X=1;top.eval();ctx.timeInc(3);
        ++sys_clock;
    };
    for(int i=0;i<64;i++)tick();
    for(int i=0;i<0x4000;i++) {
        top.AUDIO_ADDR=i;top.AUDIO_DATA=audio[2*i]|(audio[2*i+1]<<8);top.AUDIO_WE=1;tick();
    }
    top.AUDIO_WE=0;top.RESET=0;
    uint64_t limit=80000000ull+2000000ull*std::stoi(argv[5]);
    while((frame<std::stoi(argv[5]) || pre_frame<std::stoi(argv[5])) && !ctx.gotFinish() && sys_clock<limit) tick();
    // CPU words occupy the high then low 32-bit halves of each DDR beat.
    // Retain the actual first 64x32, 4bpp sprite-source bitmap for component
    // comparisons; this reads the external RAM model, not intended bus writes.
    {
        std::ofstream f(std::filesystem::path(argv[4])/"sprite-source.bin",std::ios::binary);
        for(unsigned i=0;i<1024;i++) {
            uint8_t b=memory[(0x1800000+i)/8]>>(((i&7)^4)*8);
            f.put(b);
        }
    }
    top.final();
    if(frame<std::stoi(argv[5]) || pre_frame<std::stoi(argv[5])) {std::cerr<<"native run stalled before target frame\n";return 1;}
    std::cout<<"NATIVE_COMPLETE frames="<<frame<<" cycles="<<sys_clock<<" DDR_commands="<<commands<<std::endl;
    return 0;
}
