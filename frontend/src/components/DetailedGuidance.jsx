import ReactMarkdown from 'react-markdown';

export default function DetailedGuidance({ detailed_guidance }) {
    
    const sanitizeMarkdown = (text) => {
        if (!text) return '';
        
        // 1. 【安全改动】通过 String.fromCharCode 动态生成控制字符，完美绕过正则语法报错
        const ansiControlChar = String.fromCharCode(27); // 27 即 ASCII 的 ESC 键 (\x1b 或 \u001b)
        
        // 动态创建正则表达式：匹配 \x1b[32m 等控制码
        const ansiRegex = new RegExp(`\\??${ansiControlChar}\\[\\d+m`, 'g');
      
        return text
          // 清洗动态生成的真正 ANSI 字符
          .replace(ansiRegex, '')
          // 清洗以字面量形式被转义输出的字符串 "\\u001b[32m" 
          .replace(/\\u001b\[\d+m/g, '') 
          
          // 2. 将 3 个或以上的连续换行收敛为标准的双换行
          .replace(/\n{3,}/g, '\n\n')
          .trim();
      };
      

  const cleanGuidance = sanitizeMarkdown(detailed_guidance);

  return (
    <div className="detailed-guidance-box bg-white rounded-xl p-5 border border-gray-100">
      {cleanGuidance && (
        <div className="prose prose-sm max-w-none text-gray-700 leading-relaxed 
                        prose-p:my-1 prose-ol:my-1 prose-ul:my-1 prose-li:my-0.5 custom-markdown">
          {/* ReactMarkdown 组件现在保持绝对纯净，不加任何 className */}
          <ReactMarkdown>
            {cleanGuidance}
          </ReactMarkdown>
        </div>
      )}
    </div>
  );
}
