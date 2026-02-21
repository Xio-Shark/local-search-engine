package com.localengine.storage;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;

/**
 * Delta编码器
 * 
 * 用于压缩单调递增的整数序列（如docId列表）。
 * 原理：将绝对值转换为相邻值的差值（delta），
 * 由于倒排索引的docId通常是连续的，delta值会很小，
 * 配合VarInt编码可大幅减少存储空间。
 * 
 * 示例：[10, 15, 20, 25] -> [10, 5, 5, 5]
 */
public final class DeltaCodec {
    
    private DeltaCodec() {
        // 工具类，禁止实例化
    }
    
    /**
     * 对单调递增序列进行Delta编码
     * 
     * @param sortedValues 非负单调递增序列
     * @return Delta编码后的数组
     * @throws IllegalArgumentException 如果输入非单调递增或为null
     */
    public static int[] encode(int[] sortedValues) {
        if (sortedValues == null) {
            throw new IllegalArgumentException("输入数组不能为null");
        }
        if (sortedValues.length == 0) {
            return new int[0];
        }
        
        // 验证单调递增
        for (int i = 1; i < sortedValues.length; i++) {
            if (sortedValues[i] < sortedValues[i - 1]) {
                throw new IllegalArgumentException(
                    "输入必须是非负单调递增序列，在位置 " + i + " 处违反"
                );
            }
        }
        
        int[] deltas = new int[sortedValues.length];
        deltas[0] = sortedValues[0]; // 第一个值保持原样
        
        for (int i = 1; i < sortedValues.length; i++) {
            deltas[i] = sortedValues[i] - sortedValues[i - 1];
        }
        
        return deltas;
    }
    
    /**
     * 从Delta编码还原原始序列
     * 
     * @param deltas Delta编码后的数组
     * @return 还原后的原始序列
     * @throws IllegalArgumentException 如果输入为null
     */
    public static int[] decode(int[] deltas) {
        if (deltas == null) {
            throw new IllegalArgumentException("输入数组不能为null");
        }
        if (deltas.length == 0) {
            return new int[0];
        }
        
        int[] values = new int[deltas.length];
        values[0] = deltas[0];
        
        for (int i = 1; i < deltas.length; i++) {
            values[i] = values[i - 1] + deltas[i];
        }
        
        return values;
    }
    
    /**
     * Delta编码 + VarInt组合编码，直接写入输出流
     * 
     * @param sortedValues 非负单调递增序列
     * @param out 输出流
     * @throws IOException IO异常
     * @throws IllegalArgumentException 如果输入非单调递增
     */
    public static void encodeDeltaVarInt(int[] sortedValues, OutputStream out) throws IOException {
        if (sortedValues == null || sortedValues.length == 0) {
            return;
        }
        
        // 验证单调递增
        for (int i = 1; i < sortedValues.length; i++) {
            if (sortedValues[i] < sortedValues[i - 1]) {
                throw new IllegalArgumentException(
                    "输入必须是非负单调递增序列，在位置 " + i + " 处违反"
                );
            }
        }
        
        // 写入第一个值
        VarIntCodec.writeVarInt(sortedValues[0], out);
        
        // 写入delta值
        for (int i = 1; i < sortedValues.length; i++) {
            int delta = sortedValues[i] - sortedValues[i - 1];
            VarIntCodec.writeVarInt(delta, out);
        }
    }
    
    /**
     * 从输入流读取Delta+VarInt编码的数据并解码
     * 
     * @param count 期望读取的值数量
     * @param in 输入流
     * @return 解码后的原始序列
     * @throws IOException IO异常或数据不足
     */
    public static int[] decodeDeltaVarInt(int count, InputStream in) throws IOException {
        if (count <= 0) {
            return new int[0];
        }
        
        int[] values = new int[count];
        
        // 读取第一个值
        int first = VarIntCodec.readVarInt(in);
        if (first == -1) {
            throw new IOException("流意外结束，无法读取第一个值");
        }
        values[0] = first;
        
        // 读取delta并还原
        for (int i = 1; i < count; i++) {
            int delta = VarIntCodec.readVarInt(in);
            if (delta == -1) {
                throw new IOException("流意外结束，在位置 " + i + " 处");
            }
            values[i] = values[i - 1] + delta;
        }
        
        return values;
    }
    
    /**
     * 预估Delta+VarInt编码后的大小（字节数）
     * 
     * 用于预先分配缓冲区或检查大小限制
     * 
     * @param sortedValues 非负单调递增序列
     * @return 预估编码大小（字节）
     * @throws IllegalArgumentException 如果输入非单调递增
     */
    public static int estimateEncodedSize(int[] sortedValues) {
        if (sortedValues == null || sortedValues.length == 0) {
            return 0;
        }
        
        // 验证单调递增
        for (int i = 1; i < sortedValues.length; i++) {
            if (sortedValues[i] < sortedValues[i - 1]) {
                throw new IllegalArgumentException(
                    "输入必须是非负单调递增序列，在位置 " + i + " 处违反"
                );
            }
        }
        
        int size = VarIntCodec.varIntSize(sortedValues[0]);
        
        for (int i = 1; i < sortedValues.length; i++) {
            int delta = sortedValues[i] - sortedValues[i - 1];
            size += VarIntCodec.varIntSize(delta);
        }
        
        return size;
    }
}
