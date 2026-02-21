package com.localengine.storage;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.params.provider.ValueSource;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.ByteBuffer;

import static org.junit.jupiter.api.Assertions.*;

/**
 * 编解码器单元测试
 * 
 * 测试 VarIntCodec 和 DeltaCodec 的正确性
 */
class CodecTest {
    
    // ==================== VarIntCodec 测试 ====================
    
    @Test
    @DisplayName("VarInt边界值编码解码测试")
    void testVarIntBoundaryValues() throws IOException {
        int[] testValues = {0, 1, 127, 128, 16383, 16384, Integer.MAX_VALUE};
        
        for (int value : testValues) {
            ByteArrayOutputStream baos = new ByteArrayOutputStream();
            VarIntCodec.writeVarInt(value, baos);
            
            ByteArrayInputStream bais = new ByteArrayInputStream(baos.toByteArray());
            int decoded = VarIntCodec.readVarInt(bais);
            
            assertEquals(value, decoded, "VarInt编解码失败，原值: " + value);
            assertEquals(-1, bais.read(), "流应该有且仅有VarInt数据");
        }
    }
    
    @Test
    @DisplayName("VarInt序列round-trip测试")
    void testVarIntRoundTrip() throws IOException {
        int[] testValues = {0, 1, 50, 100, 127, 128, 255, 256, 1000, 5000, 10000, 
                           50000, 100000, 1000000, Integer.MAX_VALUE};
        
        ByteArrayOutputStream baos = new ByteArrayOutputStream();
        for (int value : testValues) {
            VarIntCodec.writeVarInt(value, baos);
        }
        
        ByteArrayInputStream bais = new ByteArrayInputStream(baos.toByteArray());
        for (int expected : testValues) {
            int actual = VarIntCodec.readVarInt(bais);
            assertEquals(expected, actual);
        }
    }
    
    @Test
    @DisplayName("VarInt负数应该抛出异常")
    void testVarIntNegativeValue() {
        assertThrows(IllegalArgumentException.class, () -> {
            VarIntCodec.writeVarInt(-1, new ByteArrayOutputStream());
        });
    }
    
    @Test
    @DisplayName("VarInt ByteBuffer编码解码测试")
    void testVarIntByteBuffer() throws IOException {
        int[] testValues = {0, 127, 128, 1000, 50000, Integer.MAX_VALUE};
        
        // 计算所需缓冲区大小
        int totalSize = 0;
        for (int value : testValues) {
            totalSize += VarIntCodec.varIntSize(value);
        }
        
        ByteBuffer buffer = ByteBuffer.allocate(totalSize);
        for (int value : testValues) {
            VarIntCodec.writeVarInt(value, buffer);
        }
        
        buffer.flip();
        for (int expected : testValues) {
            int actual = VarIntCodec.readVarInt(buffer);
            assertEquals(expected, actual);
        }
    }
    
    @ParameterizedTest
    @CsvSource({
        "0, 1",
        "1, 1",
        "127, 1",
        "128, 2",
        "16383, 2",
        "16384, 3",
        "2097151, 3",
        "2097152, 4",
        "268435455, 4",
        "268435456, 5",
        "2147483647, 5"
    })
    @DisplayName("VarInt大小计算测试")
    void testVarIntSize(int value, int expectedSize) {
        assertEquals(expectedSize, VarIntCodec.varIntSize(value));
    }
    
    // ==================== VarLongCodec 测试 ====================
    
    @Test
    @DisplayName("VarLong边界值测试")
    void testVarLongBoundaryValues() throws IOException {
        long[] testValues = {0L, 1L, 127L, 128L, 16383L, 16384L, 
                            Integer.MAX_VALUE, Long.MAX_VALUE};
        
        for (long value : testValues) {
            ByteArrayOutputStream baos = new ByteArrayOutputStream();
            VarIntCodec.writeVarLong(value, baos);
            
            ByteArrayInputStream bais = new ByteArrayInputStream(baos.toByteArray());
            long decoded = VarIntCodec.readVarLong(bais);
            
            assertEquals(value, decoded, "VarLong编解码失败，原值: " + value);
        }
    }
    
    // ==================== DeltaCodec 测试 ====================
    
    @Test
    @DisplayName("Delta编码解码基本测试")
    void testDeltaEncodeDecode() {
        int[] original = {10, 15, 20, 25, 30};
        int[] expectedDeltas = {10, 5, 5, 5, 5};
        
        int[] encoded = DeltaCodec.encode(original);
        assertArrayEquals(expectedDeltas, encoded);
        
        int[] decoded = DeltaCodec.decode(encoded);
        assertArrayEquals(original, decoded);
    }
    
    @Test
    @DisplayName("Delta编码非单调序列应该抛出异常")
    void testDeltaNonMonotonic() {
        int[] nonMonotonic = {10, 15, 12, 20};
        assertThrows(IllegalArgumentException.class, () -> {
            DeltaCodec.encode(nonMonotonic);
        });
    }
    
    @Test
    @DisplayName("Delta编码空数组和单元素数组")
    void testDeltaEdgeCases() {
        // 空数组
        int[] empty = {};
        assertArrayEquals(empty, DeltaCodec.encode(empty));
        assertArrayEquals(empty, DeltaCodec.decode(empty));
        
        // 单元素数组
        int[] single = {42};
        assertArrayEquals(single, DeltaCodec.encode(single));
        assertArrayEquals(single, DeltaCodec.decode(single));
    }
    
    @Test
    @DisplayName("Delta+VarInt组合编码测试")
    void testDeltaVarIntRoundTrip() throws IOException {
        int[] original = {0, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000};
        
        ByteArrayOutputStream baos = new ByteArrayOutputStream();
        DeltaCodec.encodeDeltaVarInt(original, baos);
        
        ByteArrayInputStream bais = new ByteArrayInputStream(baos.toByteArray());
        int[] decoded = DeltaCodec.decodeDeltaVarInt(original.length, bais);
        
        assertArrayEquals(original, decoded);
    }
    
    @Test
    @DisplayName("Delta+VarInt大数据集测试")
    void testDeltaVarIntLargeDataset() throws IOException {
        // 生成1000个递增序列
        int[] original = new int[1000];
        for (int i = 0; i < 1000; i++) {
            original[i] = i * 10; // 步长10的等差数列
        }
        
        ByteArrayOutputStream baos = new ByteArrayOutputStream();
        DeltaCodec.encodeDeltaVarInt(original, baos);
        
        // 验证预估大小正确性
        int estimatedSize = DeltaCodec.estimateEncodedSize(original);
        assertEquals(baos.size(), estimatedSize);
        
        ByteArrayInputStream bais = new ByteArrayInputStream(baos.toByteArray());
        int[] decoded = DeltaCodec.decodeDeltaVarInt(original.length, bais);
        
        assertArrayEquals(original, decoded);
    }
    
    @Test
    @DisplayName("Delta预估大小测试")
    void testEstimateEncodedSize() {
        int[] values = {0, 128, 256, 1000};
        int estimated = DeltaCodec.estimateEncodedSize(values);
        
        // 手动计算：0(1B) + 128(2B) + 128(2B) + 744(2B) = 7B
        assertTrue(estimated > 0);
        
        // 验证预估与实际一致
        try {
            ByteArrayOutputStream baos = new ByteArrayOutputStream();
            DeltaCodec.encodeDeltaVarInt(values, baos);
            assertEquals(baos.size(), estimated);
        } catch (IOException e) {
            fail("不应该抛出异常");
        }
    }
    
    @ParameterizedTest
    @ValueSource(ints = {0, 1, 10, 100, 1000, 10000})
    @DisplayName("Delta+VarInt随机序列测试")
    void testRandomSequences(int count) throws IOException {
        // 生成随机递增序列
        int[] original = new int[count];
        int current = 0;
        for (int i = 0; i < count; i++) {
            current += (int) (Math.random() * 100) + 1; // 随机步长1-100
            original[i] = current;
        }
        
        ByteArrayOutputStream baos = new ByteArrayOutputStream();
        DeltaCodec.encodeDeltaVarInt(original, baos);
        
        ByteArrayInputStream bais = new ByteArrayInputStream(baos.toByteArray());
        int[] decoded = DeltaCodec.decodeDeltaVarInt(original.length, bais);
        
        assertArrayEquals(original, decoded);
    }
}
