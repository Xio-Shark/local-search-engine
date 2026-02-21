package com.localengine.storage;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.ByteBuffer;

/**
 * VarInt变长整数编解码器
 * 
 * 编码规则：每字节7位有效数据，最高位为续接标志
 * - 最高位为1：表示后续还有字节
 * - 最高位为0：表示这是最后一个字节
 * 
 * 优点：小数值占用更少字节，适合压缩频繁出现的小整数
 */
public final class VarIntCodec {
    
    private VarIntCodec() {
        // 工具类，禁止实例化
    }
    
    /**
     * 将int值编码为VarInt并写入输出流
     * 
     * @param value 要编码的值（必须非负）
     * @param out 输出流
     * @throws IOException IO异常
     * @throws IllegalArgumentException 如果value为负数
     */
    public static void writeVarInt(int value, OutputStream out) throws IOException {
        if (value < 0) {
            throw new IllegalArgumentException("VarInt不支持负数: " + value);
        }
        
        // 循环处理，每次取7位
        while ((value & ~0x7F) != 0) {
            // 还有后续字节：当前字节最高位置1
            out.write((value & 0x7F) | 0x80);
            value >>>= 7;
        }
        // 最后一个字节：最高位置0
        out.write(value & 0x7F);
    }
    
    /**
     * 从输入流读取VarInt并解码为int
     * 
     * @param in 输入流
     * @return 解码后的值，流结束返回-1
     * @throws IOException IO异常
     */
    public static int readVarInt(InputStream in) throws IOException {
        int result = 0;
        int shift = 0;
        
        while (shift < 32) {
            int b = in.read();
            if (b == -1) {
                return shift == 0 ? -1 : result; // 流结束
            }
            
            // 取低7位，左移后或到结果中
            result |= (b & 0x7F) << shift;
            
            // 检查最高位：为0表示这是最后一个字节
            if ((b & 0x80) == 0) {
                return result;
            }
            
            shift += 7;
        }
        
        throw new IOException("VarInt超过32位范围");
    }
    
    /**
     * 将int值编码为VarInt并写入ByteBuffer
     * 
     * @param value 要编码的值（必须非负）
     * @param buf 字节缓冲区
     * @throws IllegalArgumentException 如果value为负数
     */
    public static void writeVarInt(int value, ByteBuffer buf) {
        if (value < 0) {
            throw new IllegalArgumentException("VarInt不支持负数: " + value);
        }
        
        while ((value & ~0x7F) != 0) {
            buf.put((byte) ((value & 0x7F) | 0x80));
            value >>>= 7;
        }
        buf.put((byte) (value & 0x7F));
    }
    
    /**
     * 从ByteBuffer读取VarInt并解码为int
     * 
     * @param buf 字节缓冲区
     * @return 解码后的值
     * @throws IOException 如果VarInt格式错误或缓冲区不足
     */
    public static int readVarInt(ByteBuffer buf) throws IOException {
        int result = 0;
        int shift = 0;
        
        while (shift < 32) {
            if (!buf.hasRemaining()) {
                throw new IOException("ByteBuffer不足，无法读取完整VarInt");
            }
            
            int b = buf.get() & 0xFF;
            result |= (b & 0x7F) << shift;
            
            if ((b & 0x80) == 0) {
                return result;
            }
            
            shift += 7;
        }
        
        throw new IOException("VarInt超过32位范围");
    }
    
    /**
     * 将long值编码为VarLong并写入输出流
     * 
     * @param value 要编码的值（必须非负）
     * @param out 输出流
     * @throws IOException IO异常
     * @throws IllegalArgumentException 如果value为负数
     */
    public static void writeVarLong(long value, OutputStream out) throws IOException {
        if (value < 0) {
            throw new IllegalArgumentException("VarLong不支持负数: " + value);
        }
        
        while ((value & ~0x7FL) != 0) {
            out.write((int) ((value & 0x7F) | 0x80));
            value >>>= 7;
        }
        out.write((int) (value & 0x7F));
    }
    
    /**
     * 从输入流读取VarLong并解码为long
     * 
     * @param in 输入流
     * @return 解码后的值，流结束返回-1
     * @throws IOException IO异常
     */
    public static long readVarLong(InputStream in) throws IOException {
        long result = 0;
        int shift = 0;
        
        while (shift < 64) {
            int b = in.read();
            if (b == -1) {
                return shift == 0 ? -1 : result;
            }
            
            result |= (long) (b & 0x7F) << shift;
            
            if ((b & 0x80) == 0) {
                return result;
            }
            
            shift += 7;
        }
        
        throw new IOException("VarLong超过64位范围");
    }
    
    /**
     * 计算int值编码为VarInt所需的字节数
     * 
     * @param value 要编码的值（必须非负）
     * @return 所需字节数
     * @throws IllegalArgumentException 如果value为负数
     */
    public static int varIntSize(int value) {
        if (value < 0) {
            throw new IllegalArgumentException("VarInt不支持负数: " + value);
        }
        
        int size = 1;
        while ((value & ~0x7F) != 0) {
            size++;
            value >>>= 7;
        }
        return size;
    }
    
    /**
     * 计算long值编码为VarLong所需的字节数
     * 
     * @param value 要编码的值（必须非负）
     * @return 所需字节数
     * @throws IllegalArgumentException 如果value为负数
     */
    public static int varLongSize(long value) {
        if (value < 0) {
            throw new IllegalArgumentException("VarLong不支持负数: " + value);
        }
        
        int size = 1;
        while ((value & ~0x7FL) != 0) {
            size++;
            value >>>= 7;
        }
        return size;
    }
}
