package com.localengine.storage;

import com.localengine.config.Constants;

import java.io.File;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.NavigableMap;
import java.util.Optional;
import java.util.TreeMap;

/**
 * 词典文件读取器，启动时全量加载词条并提供查找能力。
 */
public final class DictionaryReader implements AutoCloseable {
    private final TreeMap<String, TermEntry> entriesByTerm = new TreeMap<>();

    /**
     * 构造读取器并完成词典全量加载。
     *
     * @param file 词典文件
     * @throws IOException 文件损坏或解析失败时抛出
     */
    public DictionaryReader(File file) throws IOException {
        if (file == null) {
            throw new IllegalArgumentException("词典文件不能为空");
        }
        try (RandomAccessFile randomAccessFile = new RandomAccessFile(file, "r")) {
            long dataLength = StorageFileUtil.verifyCrc32Footer(randomAccessFile, file.getName());
            randomAccessFile.seek(0L);

            int magic = randomAccessFile.readInt();
            if (magic != Constants.DICT_MAGIC) {
                throw new IOException("词典文件 magic 不匹配: " + file.getName());
            }
            short version = randomAccessFile.readShort();
            if (version != Constants.FORMAT_VERSION) {
                throw new IOException("词典文件版本不支持: " + version);
            }

            int termCount = randomAccessFile.readInt();
            if (termCount < 0) {
                throw new IOException("词典termCount非法: " + termCount + ", file=" + file.getAbsolutePath());
            }
            String previousTerm = null;
            for (int index = 0; index < termCount; index++) {
                int termLength = StorageFileUtil.readVarInt(randomAccessFile);
                if (termLength < 0) {
                    throw new IOException("词项长度非法: index=" + index + ", termLength=" + termLength);
                }
                byte[] termBytes = new byte[termLength];
                randomAccessFile.readFully(termBytes);
                String term = new String(termBytes, StandardCharsets.UTF_8);
                if (previousTerm != null && term.compareTo(previousTerm) <= 0) {
                    throw new IOException("词典词序损坏，term 未严格递增: " + term);
                }
                int docFreq = StorageFileUtil.readVarInt(randomAccessFile);
                if (docFreq < 0) {
                    throw new IOException("docFreq非法: term=" + term + ", docFreq=" + docFreq);
                }
                long postingsOffset = randomAccessFile.readLong();
                long positionsOffset = randomAccessFile.readLong();
                if (postingsOffset < 0 || positionsOffset < 0) {
                    throw new IOException("offset非法: term=" + term + ", postingsOffset=" + postingsOffset + ", positionsOffset=" + positionsOffset);
                }
                entriesByTerm.put(term, new TermEntry(term, docFreq, postingsOffset, positionsOffset));
                previousTerm = term;
            }

            if (randomAccessFile.getFilePointer() != dataLength) {
                throw new IOException("词典文件包含未解析字节，可能已损坏: " + file.getName());
            }
        }
    }

    /**
     * 精确查找词项对应词条。
     *
     * @param term 词项
     * @return 命中的词条或空
     */
    public Optional<TermEntry> lookup(String term) {
        return Optional.ofNullable(entriesByTerm.get(term));
    }

    /**
     * 按前缀查找词条，返回按字典序排列的结果。
     *
     * @param prefix 前缀
     * @return 匹配词条列表
     */
    public List<TermEntry> prefixSearch(String prefix) {
        if (prefix == null) {
            return List.of();
        }
        String upperBound = prefix + '\uffff';
        NavigableMap<String, TermEntry> subMap = entriesByTerm.subMap(prefix, true, upperBound, true);
        return new ArrayList<>(subMap.values());
    }

    /**
     * 获取词典词条数量。
     *
     * @return 词条数量
     */
    public int getTermCount() {
        return entriesByTerm.size();
    }

    /**
     * 判断词典中是否包含指定词项。
     *
     * @param term 词项
     * @return 命中返回true
     */
    public boolean contains(String term) {
        return entriesByTerm.containsKey(term);
    }

    /**
     * 返回全部词项集合（按字典序）。
     *
     * @return 不可修改词项集合
     */
    public java.util.Collection<String> allTerms() {
        return java.util.List.copyOf(entriesByTerm.navigableKeySet());
    }

    @Override
    public void close() throws IOException {
    }
}
